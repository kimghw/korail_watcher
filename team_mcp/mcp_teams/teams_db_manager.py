"""
Teams DB Manager
Teams 채팅 정보의 데이터베이스 관리
한글 이름 저장 및 채팅 목록 동기화
"""

import json
import sqlite3
import os
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class TeamsDBManager:
    """Teams 채팅 DB 관리"""

    def __init__(self, db_path: Optional[str] = None):
        """
        데이터베이스 초기화

        Args:
            db_path: 데이터베이스 파일 경로. None이면 DB_PATH 환경변수 또는 기본값 사용.
        """
        if db_path is None:
            db_path = os.getenv("DB_PATH", "database/auth.db")

        # Resolve to an absolute path
        resolved_path = os.path.expanduser(db_path)
        if not os.path.isabs(resolved_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            resolved_path = os.path.join(base_dir, resolved_path)

        self.db_path = resolved_path
        self._ensure_tables()

    def _ensure_tables(self):
        """Teams 관련 테이블 생성"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.executescript("""
                -- Teams 채팅 정보 테이블
                CREATE TABLE IF NOT EXISTS teams_chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    chat_type TEXT DEFAULT 'unknown',
                    topic TEXT,
                    topic_kr TEXT,
                    member_count INTEGER DEFAULT 0,
                    members_json TEXT,
                    peer_user_name TEXT,
                    peer_user_email TEXT,
                    last_message_preview TEXT,
                    last_message_time TEXT,
                    last_sent_at TEXT,
                    last_received_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_sync_at TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    UNIQUE(user_id, chat_id)
                );

                -- 인덱스 생성
                CREATE INDEX IF NOT EXISTS idx_teams_chats_user_id ON teams_chats(user_id);
                CREATE INDEX IF NOT EXISTS idx_teams_chats_topic_kr ON teams_chats(topic_kr);
                CREATE INDEX IF NOT EXISTS idx_teams_chats_peer_user_name ON teams_chats(peer_user_name);
                CREATE INDEX IF NOT EXISTS idx_teams_chats_is_active ON teams_chats(is_active);
            """)
            conn.commit()
            logger.info("Teams tables created successfully")
        except Exception as e:
            logger.error(f"[ERROR] Failed to create Teams tables: {e}")
            raise
        finally:
            conn.close()

    def _contains_hangul(self, text: str) -> bool:
        """한글 포함 여부 확인"""
        try:
            return any("\uac00" <= ch <= "\ud7a3" for ch in text)
        except Exception:
            return False

    async def find_chat_by_name(self, user_id: str, recipient_name: str) -> Optional[str]:
        """
        사용자 이름으로 chat_id 검색 (활성/비활성 모두 검색, 활성 우선)

        Args:
            user_id: 사용자 ID (이메일)
            recipient_name: 검색할 상대방 이름

        Returns:
            chat_id 또는 None
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT chat_id FROM teams_chats
                WHERE user_id = ?
                AND (
                    LOWER(peer_user_name) LIKE LOWER(?)
                    OR LOWER(topic) LIKE LOWER(?)
                    OR LOWER(topic_kr) LIKE LOWER(?)
                )
                ORDER BY
                    is_active DESC,
                    last_message_time DESC
                LIMIT 1
                """,
                (user_id, f"%{recipient_name}%", f"%{recipient_name}%", f"%{recipient_name}%")
            )

            row = cursor.fetchone()
            if row:
                chat_id = row[0]
                logger.info(f"사용자 '{recipient_name}' 채팅 찾음: {chat_id}")
                return chat_id
            else:
                logger.warning(f"[WARN] 사용자 '{recipient_name}' 채팅을 찾을 수 없습니다")
                return None

        except Exception as e:
            logger.error(f"[ERROR] 채팅 검색 오류: {str(e)}")
            return None
        finally:
            conn.close()

    async def save_korean_name(
        self,
        user_id: str,
        topic_kr: str,
        chat_id: Optional[str] = None,
        topic_en: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        채팅의 한글 이름을 저장

        Args:
            user_id: 사용자 ID (이메일)
            topic_kr: 한글 이름
            chat_id: 채팅 ID (선택)
            topic_en: 영문 이름 (선택, chat_id가 없을 때 검색용)

        Returns:
            성공/실패 결과
        """
        if not topic_kr:
            return {"success": False, "message": "한글 이름(topic_kr)이 필요합니다"}

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # chat_id가 없으면 topic_en으로 검색
            if not chat_id and topic_en:
                cursor.execute(
                    """
                    SELECT chat_id FROM teams_chats
                    WHERE user_id = ?
                    AND is_active = TRUE
                    AND (
                        LOWER(peer_user_name) LIKE LOWER(?)
                        OR LOWER(topic) LIKE LOWER(?)
                    )
                    ORDER BY last_message_time DESC
                    LIMIT 1
                    """,
                    (user_id, f"%{topic_en}%", f"%{topic_en}%")
                )

                row = cursor.fetchone()
                if row:
                    chat_id = row[0]
                    logger.info(f"영문 이름 '{topic_en}'으로 채팅 찾음: {chat_id}")
                else:
                    return {"success": False, "message": f"영문 이름 '{topic_en}'으로 채팅을 찾을 수 없습니다"}

            # chat_id로 한글 이름 업데이트
            if chat_id:
                cursor.execute(
                    """
                    UPDATE teams_chats
                    SET topic_kr = ?, updated_at = ?
                    WHERE user_id = ? AND chat_id = ?
                    """,
                    (topic_kr, datetime.now(timezone.utc).isoformat(), user_id, chat_id)
                )
                conn.commit()

                if cursor.rowcount > 0:
                    logger.info(f"한글 이름 저장: {chat_id} -> {topic_kr}")
                    return {
                        "success": True,
                        "message": f"한글 이름 '{topic_kr}' 저장 완료",
                        "chat_id": chat_id
                    }
                else:
                    return {"success": False, "message": f"chat_id '{chat_id}'를 찾을 수 없습니다"}
            else:
                return {"success": False, "message": "chat_id 또는 topic_en이 필요합니다"}

        except Exception as e:
            logger.error(f"[ERROR] 한글 이름 저장 오류: {str(e)}")
            return {"success": False, "message": f"오류 발생: {str(e)}"}
        finally:
            conn.close()

    async def save_korean_names_batch(
        self,
        user_id: str,
        names: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        여러 채팅의 한글 이름을 한 번에 저장

        Args:
            user_id: 사용자 ID (이메일)
            names: [{"topic_en": "영문", "topic_kr": "한글"}, ...] 형식의 리스트

        Returns:
            {"success": True, "saved": 3, "failed": 1, "results": [...]}
        """
        results = []
        saved_count = 0
        failed_count = 0

        for item in names:
            topic_en = item.get("topic_en", "")
            topic_kr = item.get("topic_kr", "")

            if not topic_en or not topic_kr:
                results.append({
                    "topic_en": topic_en,
                    "topic_kr": topic_kr,
                    "success": False,
                    "message": "topic_en과 topic_kr이 모두 필요합니다"
                })
                failed_count += 1
                continue

            result = await self.save_korean_name(user_id, topic_kr, None, topic_en)
            results.append({
                "topic_en": topic_en,
                "topic_kr": topic_kr,
                **result
            })

            if result.get("success"):
                saved_count += 1
            else:
                failed_count += 1

        return {
            "success": True,
            "saved": saved_count,
            "failed": failed_count,
            "total": len(names),
            "results": results
        }

    async def sync_chats_to_db(self, user_id: str, chats: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        채팅 목록을 DB에 동기화

        Args:
            user_id: 사용자 ID (이메일)
            chats: Graph API에서 조회한 채팅 목록

        Returns:
            동기화 결과
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()

            # 현재 조회된 chat_id들
            current_chat_ids = {chat.get("id") for chat in chats}

            # 기존 DB의 활성 chat_id들 조회
            cursor.execute(
                "SELECT chat_id FROM teams_chats WHERE user_id = ? AND is_active = TRUE",
                (user_id,)
            )
            existing_chat_ids = {row[0] for row in cursor.fetchall()}

            # 삭제된 채팅 비활성화
            deleted_chat_ids = existing_chat_ids - current_chat_ids
            for chat_id in deleted_chat_ids:
                cursor.execute(
                    "UPDATE teams_chats SET is_active = FALSE, updated_at = ? WHERE user_id = ? AND chat_id = ?",
                    (now, user_id, chat_id)
                )

            # 각 채팅 정보를 DB에 UPSERT
            for chat in chats:
                chat_id = chat.get("id")
                chat_type = chat.get("chatType") or chat.get("chat_type", "unknown")
                topic = chat.get("topic", "")

                # 멤버 정보 추출
                members = chat.get("members", [])
                member_count = len(members)
                members_json = json.dumps(members, ensure_ascii=False)

                # 1:1 채팅인 경우 상대방 정보 추출
                peer_user_name = None
                peer_user_email = None
                if chat_type == "oneOnOne" and len(members) >= 2:
                    peer_member = members[1] if len(members) > 1 else members[0]
                    peer_user_name = peer_member.get("displayName", "")
                    peer_user_email = peer_member.get("email", "")

                # 한글 이름(topic_kr) 추정
                topic_kr = None
                if chat_type == "oneOnOne" and peer_user_name:
                    if self._contains_hangul(peer_user_name):
                        topic_kr = peer_user_name
                if not topic_kr and topic:
                    if self._contains_hangul(topic):
                        topic_kr = topic

                # 마지막 메시지 정보
                last_message_preview = ""
                if chat.get("lastMessagePreview"):
                    body = chat["lastMessagePreview"].get("body", {})
                    last_message_preview = body.get("content", "") if isinstance(body, dict) else ""
                last_message_time = chat.get("lastUpdatedDateTime", "")

                # DB에 UPSERT
                cursor.execute(
                    """
                    INSERT INTO teams_chats (
                        user_id, chat_id, chat_type, topic, topic_kr,
                        member_count, members_json, peer_user_name, peer_user_email,
                        last_message_preview, last_message_time,
                        created_at, updated_at, last_sync_at, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE)
                    ON CONFLICT(user_id, chat_id) DO UPDATE SET
                        chat_type = excluded.chat_type,
                        topic = excluded.topic,
                        topic_kr = COALESCE(teams_chats.topic_kr, excluded.topic_kr),
                        member_count = excluded.member_count,
                        members_json = excluded.members_json,
                        peer_user_name = excluded.peer_user_name,
                        peer_user_email = excluded.peer_user_email,
                        last_message_preview = excluded.last_message_preview,
                        last_message_time = excluded.last_message_time,
                        updated_at = excluded.updated_at,
                        last_sync_at = excluded.last_sync_at,
                        is_active = TRUE
                    """,
                    (
                        user_id, chat_id, chat_type, topic, topic_kr,
                        member_count, members_json, peer_user_name, peer_user_email,
                        last_message_preview, last_message_time,
                        now, now, now
                    )
                )

            conn.commit()
            logger.info(f"DB 동기화 완료: {len(chats)}개 채팅, {len(deleted_chat_ids)}개 비활성화")

            return {
                "success": True,
                "synced": len(chats),
                "deactivated": len(deleted_chat_ids),
            }

        except Exception as e:
            logger.error(f"[ERROR] DB 동기화 오류: {str(e)}")
            conn.rollback()
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    async def get_chats_with_korean_names(self, user_id: str) -> List[Dict[str, Any]]:
        """
        사용자의 채팅 목록 조회 (한글 이름 포함)

        Args:
            user_id: 사용자 ID (이메일)

        Returns:
            채팅 목록 (topic_kr 포함)
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM teams_chats
                WHERE user_id = ? AND is_active = TRUE
                ORDER BY last_message_time DESC
                """,
                (user_id,)
            )

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"[ERROR] 채팅 목록 조회 오류: {str(e)}")
            return []
        finally:
            conn.close()

    async def get_chats_without_korean_names(self, user_id: str) -> List[Dict[str, Any]]:
        """
        한글 이름이 없는 채팅 목록 조회

        Args:
            user_id: 사용자 ID (이메일)

        Returns:
            한글 이름이 없는 채팅 목록
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM teams_chats
                WHERE user_id = ? AND is_active = TRUE
                AND (topic_kr IS NULL OR topic_kr = '')
                AND (peer_user_name IS NOT NULL AND peer_user_name != '')
                ORDER BY last_message_time DESC
                """,
                (user_id,)
            )

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"[ERROR] 채팅 목록 조회 오류: {str(e)}")
            return []
        finally:
            conn.close()

    async def update_last_sent_at(self, user_id: str, chat_id: str) -> None:
        """
        메시지 전송 시간 업데이트

        Args:
            user_id: 사용자 ID
            chat_id: 채팅 ID
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "UPDATE teams_chats SET last_sent_at = ?, updated_at = ? WHERE user_id = ? AND chat_id = ?",
                (now, now, user_id, chat_id)
            )
            conn.commit()
        except Exception as e:
            logger.warning(f"[WARN] DB 업데이트 실패 (무시): {str(e)}")
        finally:
            conn.close()
