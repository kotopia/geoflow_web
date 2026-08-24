const GEOFLOW_CONTRACT_SHEET = 'GeoFlow_계약정보';
const GEOFLOW_CONTRACT_API_URL = 'https://geoflow.co.kr/api/temp/contracts/';
const GEOFLOW_API_KEY_PROPERTY = 'GEOFLOW_TEMP_CONTRACT_API_KEY';

const GEOFLOW_CONTRACT_HEADERS = [
  '계약ID', '레거시ID', '계약번호', '계약명', '프로젝트ID', '프로젝트코드', '프로젝트명',
  '전체프로젝트코드', '착수일', '준공일', '계약금액', '상태', '계약유형', '구분',
  '발주처ID', '발주처', '하도급처ID', '하도급처', '조직ID', '조직', '비고',
  '확장정보(JSON)', '생성일시', '수정일시', '프로젝트전체(JSON)'
];

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('GeoFlow')
    .addItem('계약정보 새로고침', 'syncGeoFlowContracts')
    .addSeparator()
    .addItem('API 키 설정', 'setGeoFlowContractApiKey')
    .addItem('1시간 자동 새로고침 설치', 'installGeoFlowHourlyTrigger')
    .addItem('자동 새로고침 해제', 'removeGeoFlowSyncTriggers')
    .addToUi();
}

function setGeoFlowContractApiKey() {
  const ui = SpreadsheetApp.getUi();
  const response = ui.prompt(
    'GeoFlow 임시 API 키 설정',
    '서버에서 발급된 임시 API 키를 입력하세요. 값은 Script Properties에만 저장됩니다.',
    ui.ButtonSet.OK_CANCEL
  );
  if (response.getSelectedButton() !== ui.Button.OK) return;

  const key = response.getResponseText().trim();
  if (!key) {
    ui.alert('API 키가 비어 있습니다.');
    return;
  }

  PropertiesService.getScriptProperties().setProperty(GEOFLOW_API_KEY_PROPERTY, key);
  ui.alert('GeoFlow 임시 API 키가 저장되었습니다.');
}

function syncGeoFlowContracts() {
  const key = PropertiesService.getScriptProperties().getProperty(GEOFLOW_API_KEY_PROPERTY);
  if (!key) {
    throw new Error('GeoFlow API 키가 설정되지 않았습니다. 메뉴에서 “API 키 설정”을 먼저 실행하세요.');
  }

  const response = UrlFetchApp.fetch(GEOFLOW_CONTRACT_API_URL, {
    method: 'get',
    headers: {
      'X-GeoFlow-Temp-Key': key,
      'Accept': 'application/json'
    },
    muteHttpExceptions: true,
    followRedirects: true
  });

  const status = response.getResponseCode();
  if (status === 404) {
    throw new Error('GeoFlow 임시 계약 API가 현재 비활성 상태입니다.');
  }
  if (status === 403) {
    throw new Error('GeoFlow API 인증이 거부되었습니다. API 키를 확인하세요.');
  }
  if (status !== 200) {
    throw new Error('GeoFlow 계약 API 호출 실패: HTTP ' + status);
  }

  const payload = JSON.parse(response.getContentText());
  if (!Array.isArray(payload)) {
    throw new Error('GeoFlow 계약 API 응답 형식이 예상과 다릅니다.');
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(GEOFLOW_CONTRACT_SHEET);
  if (!sheet) sheet = ss.insertSheet(GEOFLOW_CONTRACT_SHEET);

  ensureGeoFlowHeader_(sheet);

  const rows = payload.map(contract => [
    text_(contract.contract_id),
    value_(contract.legacy_id),
    text_(contract.contract_code),
    text_(contract.contract_name),
    text_(contract.project_id),
    text_(contract.project_code),
    text_(contract.project_name),
    Array.isArray(contract.project_codes) ? contract.project_codes.join(', ') : '',
    text_(contract.start_date),
    text_(contract.end_date),
    value_(contract.amount),
    text_(contract.status),
    text_(contract.kind),
    text_(contract.division),
    text_(contract.client_id),
    text_(contract.client_name),
    text_(contract.sub_client_id),
    text_(contract.sub_client_name),
    text_(contract.org_unit_id),
    text_(contract.org_unit_name),
    text_(contract.description),
    json_(contract.ext),
    text_(contract.created_at),
    text_(contract.updated_at),
    json_(contract.projects)
  ]);

  const lastRow = Math.max(sheet.getLastRow(), 2);
  sheet.getRange(2, 1, lastRow - 1, GEOFLOW_CONTRACT_HEADERS.length).clearContent();

  if (rows.length) {
    sheet.getRange(2, 1, rows.length, GEOFLOW_CONTRACT_HEADERS.length).setValues(rows);
  }

  sheet.setFrozenRows(1);
  sheet.getRange('K2:K').setNumberFormat('#,##0');
  sheet.getRange('I2:J').setNumberFormat('yyyy-mm-dd');
  sheet.autoResizeColumns(1, GEOFLOW_CONTRACT_HEADERS.length);

  PropertiesService.getDocumentProperties().setProperty(
    'GEOFLOW_CONTRACT_LAST_SYNC_AT',
    new Date().toISOString()
  );

  return rows.length;
}

function installGeoFlowHourlyTrigger() {
  removeGeoFlowSyncTriggers();
  ScriptApp.newTrigger('syncGeoFlowContracts')
    .timeBased()
    .everyHours(1)
    .create();
  SpreadsheetApp.getUi().alert('GeoFlow 계약정보를 1시간마다 새로고침하도록 설정했습니다.');
}

function removeGeoFlowSyncTriggers() {
  ScriptApp.getProjectTriggers()
    .filter(trigger => trigger.getHandlerFunction() === 'syncGeoFlowContracts')
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));
}

function ensureGeoFlowHeader_(sheet) {
  const range = sheet.getRange(1, 1, 1, GEOFLOW_CONTRACT_HEADERS.length);
  const current = range.getValues()[0];
  const needsUpdate = GEOFLOW_CONTRACT_HEADERS.some((header, index) => current[index] !== header);
  if (needsUpdate) range.setValues([GEOFLOW_CONTRACT_HEADERS]);
}

function text_(value) {
  return value === null || value === undefined ? '' : String(value);
}

function value_(value) {
  return value === null || value === undefined ? '' : value;
}

function json_(value) {
  if (value === null || value === undefined) return '';
  return JSON.stringify(value);
}
