# Temporary GeoFlow contract -> Google Sheets sync

This integration is intentionally temporary and removable.

## Scope

- GeoFlow remains the source of truth.
- Google Sheets consumes the read-only endpoint `GET /api/temp/contracts/`.
- No Google Sheet writes back to GeoFlow.
- No DB migration is required for the temporary API or the sheet sync client.
- The production API remains disabled unless explicitly activated.

## Target spreadsheet layout

The sync client writes to the tab `GeoFlow_계약정보` using these columns:

1. 계약ID
2. 레거시ID
3. 계약번호
4. 계약명
5. 프로젝트ID
6. 프로젝트코드
7. 프로젝트명
8. 전체프로젝트코드
9. 착수일
10. 준공일
11. 계약금액
12. 상태
13. 계약유형
14. 구분
15. 발주처ID
16. 발주처
17. 하도급처ID
18. 하도급처
19. 조직ID
20. 조직
21. 비고
22. 확장정보(JSON)
23. 생성일시
24. 수정일시
25. 프로젝트전체(JSON)

## Authentication

The temporary API key must never be stored in sheet cells or committed to Git.
The Apps Script client stores it in `PropertiesService.getScriptProperties()` and sends it only in the `X-GeoFlow-Temp-Key` request header.

Required script properties:

- `GEOFLOW_CONTRACT_API_URL`
- `GEOFLOW_CONTRACT_API_KEY`

The helper `setGeoFlowContractSyncConfig(apiUrl, apiKey)` writes both properties.

## Client

Source: `integrations/google_sheets/contract_sync.gs`

Primary function:

- `syncGeoFlowContracts()`

Behavior:

- calls the temporary API with the header key;
- requires HTTP 200 and a JSON array;
- preserves the first-row header contract;
- clears only old data rows in `GeoFlow_계약정보`;
- writes the latest full contract/project list;
- recreates the filter and updates the A1 note with sync time and row count.

## Production activation boundary

Activation requires exact separate operational authorization because the production runtime must set the temporary endpoint configuration and restart/reload the service. The required runtime values are:

- `TEMP_CONTRACT_LIST_API_ENABLED=1`
- `TEMP_CONTRACT_LIST_GROUP_CODE=<reviewed target group code>`
- `TEMP_CONTRACT_LIST_API_KEY=<temporary secret>`

Do not print, commit, or place the API key in Google Sheet cells.

## Removal

When the temporary integration is no longer needed:

1. disable/remove the production runtime variables and restart through a reviewed production workflow;
2. remove the `api/temp/contracts/` route and `geoflow_ops/temp_contract_list_api.py`;
3. remove `integrations/google_sheets/contract_sync.gs` if no longer used;
4. optionally keep or archive the `GeoFlow_계약정보` tab as a historical snapshot.

No schema rollback is needed because this integration introduces no DB migration.
