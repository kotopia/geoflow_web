const GEOFLOW_CONTRACT_SHEET = 'GeoFlow_계약정보';
const GEOFLOW_CONTRACT_HEADERS = [
  '계약ID', '레거시ID', '계약번호', '계약명', '프로젝트ID', '프로젝트코드', '프로젝트명',
  '전체프로젝트코드', '착수일', '준공일', '계약금액', '상태', '계약유형', '구분',
  '발주처ID', '발주처', '하도급처ID', '하도급처', '조직ID', '조직', '비고',
  '확장정보(JSON)', '생성일시', '수정일시', '프로젝트전체(JSON)'
];

/**
 * Store the temporary GeoFlow integration settings in Apps Script Properties.
 * Do not put the API key in spreadsheet cells or source code.
 */
function setGeoFlowContractSyncConfig(apiUrl, apiKey) {
  if (!apiUrl || !apiKey) {
    throw new Error('apiUrl and apiKey are required.');
  }
  PropertiesService.getScriptProperties().setProperties({
    GEOFLOW_CONTRACT_API_URL: String(apiUrl).trim(),
    GEOFLOW_CONTRACT_API_KEY: String(apiKey).trim()
  });
}

function clearGeoFlowContractSyncConfig() {
  PropertiesService.getScriptProperties().deleteAllProperties();
}

function syncGeoFlowContracts() {
  const props = PropertiesService.getScriptProperties();
  const apiUrl = props.getProperty('GEOFLOW_CONTRACT_API_URL');
  const apiKey = props.getProperty('GEOFLOW_CONTRACT_API_KEY');
  if (!apiUrl || !apiKey) {
    throw new Error('GeoFlow contract sync is not configured.');
  }

  const response = UrlFetchApp.fetch(apiUrl, {
    method: 'get',
    headers: {
      'X-GeoFlow-Temp-Key': apiKey
    },
    muteHttpExceptions: true,
    followRedirects: true
  });

  const status = response.getResponseCode();
  if (status !== 200) {
    throw new Error(`GeoFlow contract API returned HTTP ${status}.`);
  }

  const payload = JSON.parse(response.getContentText('UTF-8'));
  if (!Array.isArray(payload)) {
    throw new Error('GeoFlow contract API response is not a list.');
  }

  const rows = payload.map(contractToRow_);
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = spreadsheet.getSheetByName(GEOFLOW_CONTRACT_SHEET);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(GEOFLOW_CONTRACT_SHEET);
  }

  ensureHeader_(sheet);

  const lastRow = sheet.getLastRow();
  if (lastRow > 1) {
    sheet.getRange(2, 1, lastRow - 1, GEOFLOW_CONTRACT_HEADERS.length).clearContent();
  }

  if (rows.length > 0) {
    sheet.getRange(2, 1, rows.length, GEOFLOW_CONTRACT_HEADERS.length).setValues(rows);
  }

  sheet.setFrozenRows(1);
  if (sheet.getFilter()) {
    sheet.getFilter().remove();
  }
  sheet.getRange(1, 1, Math.max(rows.length + 1, 2), GEOFLOW_CONTRACT_HEADERS.length).createFilter();
  sheet.autoResizeColumns(1, GEOFLOW_CONTRACT_HEADERS.length);

  sheet.getRange('A1').setNote(`GeoFlow 동기화 완료: ${new Date().toISOString()} / ${rows.length}건`);
}

function contractToRow_(item) {
  const projectCodes = Array.isArray(item.project_codes) ? item.project_codes.join(', ') : '';
  return [
    value_(item.contract_id),
    value_(item.legacy_id),
    value_(item.contract_code),
    value_(item.contract_name),
    value_(item.project_id),
    value_(item.project_code),
    value_(item.project_name),
    projectCodes,
    value_(item.start_date),
    value_(item.end_date),
    numberOrBlank_(item.amount),
    value_(item.status),
    value_(item.kind),
    value_(item.division),
    value_(item.client_id),
    value_(item.client_name),
    value_(item.sub_client_id),
    value_(item.sub_client_name),
    value_(item.org_unit_id),
    value_(item.org_unit_name),
    value_(item.description),
    json_(item.ext),
    value_(item.created_at),
    value_(item.updated_at),
    json_(item.projects)
  ];
}

function ensureHeader_(sheet) {
  const current = sheet.getRange(1, 1, 1, GEOFLOW_CONTRACT_HEADERS.length).getValues()[0];
  const matches = GEOFLOW_CONTRACT_HEADERS.every((header, index) => current[index] === header);
  if (!matches) {
    sheet.getRange(1, 1, 1, GEOFLOW_CONTRACT_HEADERS.length).setValues([GEOFLOW_CONTRACT_HEADERS]);
  }
}

function value_(value) {
  return value === null || value === undefined ? '' : String(value);
}

function numberOrBlank_(value) {
  if (value === null || value === undefined || value === '') {
    return '';
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : String(value);
}

function json_(value) {
  if (value === null || value === undefined) {
    return '';
  }
  return JSON.stringify(value);
}
