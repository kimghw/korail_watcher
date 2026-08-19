---
name: azure_env_export
description: .env.ktx 의 "Azure AD OAuth" 섹션(AZURE_* 키 + 헤더 주석)만 추출해 별도 env 파일(.env.azure)로 저장. 사용자가 "azure 설정 추출", "azure env 파일", "OAuth 설정만 뽑아줘", "/azure_env_export" 등을 말하면 시작. 결과 파일은 실 시크릿 포함 — 절대 커밋 금지(.gitignore 확인).
---

# azure_env_export — Azure AD OAuth 섹션 추출

`.env.ktx` 에서 `# Azure AD OAuth ...` 섹션(헤더 주석 3줄 + `AZURE_*` 키 전부)만 잘라
별도 파일로 저장한다. team_mcp 등 Graph API 호출 컴포넌트에 Azure 자격증명만
넘겨야 할 때 사용.

> **경고**: 결과 파일에는 실 시크릿(AZURE_CLIENT_SECRET 등)이 들어간다.
> 절대 커밋하지 않으며, 값 자체를 채팅 출력에 노출하지 않는다 (키 이름만 보고).

## 인자

| 인자 | 기본값 | 의미 |
|:---|:---|:---|
| 1번째 | `.env.ktx` | 원본 env 파일 경로 |
| 2번째 | `.env.azure` | 출력 파일 경로 |

## 절차

1. **추출 실행** (Bash, 프로젝트 루트에서):

   ```bash
   bash .claude/skills/azure_env_export/export_azure.sh [<src>] [<out>]
   ```

   - 성공 시 `OK <out> (N keys)` + 키 이름 목록 출력.
   - 섹션 헤더(`# ====` 룰러 + "Azure AD OAuth")를 찾으면 헤더 주석까지 보존해 추출,
     못 찾으면 `AZURE_*` 키만 grep 하는 폴백으로 동작.
2. **gitignore 확인**: 출력 파일이 프로젝트 안이면 `.gitignore` 에 해당 파일명이
   있는지 확인, 없으면 추가한다 (실 시크릿 파일이므로 필수).
3. **결과 보고**: 출력 경로 + 추출된 키 이름 목록만 보고. **값은 출력하지 않는다.**

## DON'T

- 결과 파일이나 원본의 시크릿 값을 채팅/로그에 그대로 출력하지 않는다.
- 결과 파일을 커밋하지 않는다.
- `.env.ktx.example` 동기화 룰은 이 스킬과 무관 (키 추가/변경이 아님).
