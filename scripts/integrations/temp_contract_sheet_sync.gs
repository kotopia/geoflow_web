const GEOFLOW_CONTRACT_SYNC = Object.freeze({
  sheetName: 'GeoFlow_계약정보',
  defaultApiUrl: 'https://geoflow.co.kr/api/temp/contracts/',
  propertyApiUrl: 'GEOFLOW_TEMP_CONTRACT_API_URL',
  propertyApiKey: 'GEOFLOW_TEMP_CONTRACT_API_KEY',
  headers: [
    '계약ID',
    '레거시ID',
    '계약번호',
    '계약명',
    '프로젝트ID',
    '프로젝트코드',
    '프로젝트명',
    '전체프로젝트코드',
    '착수일',
    '준공일',
    '계약금액',
    '상태',
    '계약유형',
    '구분',
    '발주처ID',
    '발주처',
    '하도급처ID',
    '하도급처',
    '조직ID',
    '조직',
    '비고',
    '확장정보(JSON)',
    '생성일시',
    '수정일시',
    '프로젝트전체(JSON)',
  ],
});

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('GeoFlow')
    .addItem('계약정보 새로고침', 'syncGeoFlowContracts')
    .addSeparator()
    .addItem('연동 설정', 'configureGeoFlowContractSync')
    .addItem('연동 설정 삭제', 'clearGeoFlowContractSyncConfig')
    .addToUi();
}

function configureGeoFlowContractSync() {
  const ui = SpreadsheetApp.getUi();
  const props = PropertiesService.getDocumentProperties();

  const currentUrl =
    props.getProperty(GEOFLOW_CONTRACT_SYNC.propertyApiUrl) ||
    GEOFLOW_CONTRACT_SYNC.defaultApiUrl;

  const urlPrompt = ui.prompt(
    'GeoFlow 계약정보 연동 설정',
    `API URL을 확인하세요.\n기본값: ${currentUrl}`,
    ui.ButtonSet.OK_CANCEL,
  );
  if (urlPrompt.getSelectedButton() !== ui.Button.OK) {
    return;
  }

  const enteredUrl = String(urlPrompt.getResponseText() || '').trim();
  const apiUrl = enteredUrl || currentUrl;
  if (!/^https:\/\//i.test(apiUrl)) {
    ui.alert('API URL은 https:// 주소여야 합니다.');
    return;
  }

  const keyPrompt = ui.prompt(
    'GeoFlow 임시 API 키',
    '임시 읽기 전용 API 키를 입력하세요. 키는 시트 셀이 아니라 문서 속성에 저장됩니다.',
    ui.ButtonSet.OK_CANCEL,
  );
  if (keyPrompt.getSelectedButton() !== ui.Button.OK) {
    return;
  }

  const apiKey = String(keyPrompt.getResponseText() || '').trim();
  if (!apiKey) {
    ui.alert('API 키가 비어 있습니다.');
    return;
  }

  props.setProperties(
    {
      [GEOFLOW_CONTRACT_SYNC.propertyApiUrl]: apiUrl,
      [GEOFLOW_CONTRACT_SYNC.propertyApiKey]: apiKey,
    },
    false,
  );

  ui.alert('GeoFlow 계약정보 연동 설정을 저장했습니다.');
}

function clearGeoFlowContractSyncConfig() {
  const ui = SpreadsheetApp.getUi();
  const answer = ui.alert(
    'GeoFlow 연동 설정 삭제',
    '이 문서에 저장된 임시 API URL과 API 키를 삭제할까요?',
    ui.ButtonSet.YES_NO,
  );
  if (answer !== ui.Button.YES) {
    return;
  }

  const props = PropertiesService.getDocumentProperties();
  props.deleteProperty(GEOFLOW_CONTRACT_SYNC.propertyApiUrl);
  props.deleteProperty(GEOFLOW_CONTRACT_SYNC.propertyApiKey);
  ui.alert('GeoFlow 연동 설정을 삭제했습니다.');
}

function syncGeoFlowContracts() {
  const lock = LockService.getDocumentLock();
  lock.waitLock(30000);

  try {
    const props = PropertiesService.getDocumentProperties();
    const apiUrl =
      props.getProperty(GEOFLOW_CONTRACT_SYNC.propertyApiUrl) ||
      GEOFLOW_CONTRACT_SYNC.defaultApiUrl;
    const apiKey = props.getProperty(GEOFLOW_CONTRACT_SYNC.propertyApiKey);

    if (!apiKey) {
      throw new Error('GeoFlow API 키가 설정되지 않았습니다. GeoFlow > 연동 설정을 먼저 실행하세요.');
    }

    const response = UrlFetchApp.fetch(apiUrl, {
      method: 'get',
      headers: {
        'X-GeoFlow-Temp-Key': apiKey,
        Accept: 'application/json',
      },
      followRedirects: true,
      muteHttpExceptions: true,
    });

    const status = response.getResponseCode();
    const body = response.getContentText('UTF-8');

    if (status !== 200) {
      throw new Error(`GeoFlow API 호출 실패 (HTTP ${status})`);
    }

    let contracts;
    try {
      contracts = JSON.parse(body);
    } catch (err) {
      throw new Error('GeoFlow API 응답이 올바른 JSON이 아닙니다.');
    }

    if (!Array.isArray(contracts)) {
      throw new Error('GeoFlow API 응답이 계약 리스트 형식이 아닙니다.');
    }

    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    let sheet = spreadsheet.getSheetByName(GEOFLOW_CONTRACT_SYNC.sheetName);
    if (!sheet) {
      sheet = spreadsheet.insertSheet(GEOFLOW_CONTRACT_SYNC.sheetName);
    }

    ensureGeoFlowContractHeaders_(sheet);

    const rows = contracts.map(contractToSheetRow_);
    const maxRows = sheet.getMaxRows();
    if (maxRows > 1) {
      sheet
        .getRange(2, 1, maxRows - 1, GEOFLOW_CONTRACT_SYNC.headers.length)
        .clearContent();
    }

    if (rows.length > 0) {
      ensureSheetCapacity_(sheet, rows.length + 1);
      sheet
        .getRange(2, 1, rows.length, GEOFLOW_CONTRACT_SYNC.headers.length)
        .setValues(rows);
    }

    sheet.setFrozenRows(1);
    sheet.getRange(2, 11, Math.max(rows.length, 1), 1).setNumberFormat('#,##0');

    const now = Utilities.formatDate(
      new Date(),
      spreadsheet.getSpreadsheetTimeZone() || 'Asia/Seoul',
      'yyyy-MM-dd HH:mm:ss',
    );
    spreadsheet.toast(
      `계약 ${rows.length}건 동기화 완료 · ${now}`,
      'GeoFlow',
      5,
    );
  } finally {
    lock.releaseLock();
  }
}

function ensureGeoFlowContractHeaders_(sheet) {
  const expected = GEOFLOW_CONTRACT_SYNC.headers;
  const actual = sheet.getRange(1, 1, 1, expected.length).getValues()[0];
  const matches = expected.every((value, index) => String(actual[index] || '') === value);

  if (!matches) {
    sheet.getRange(1, 1, 1, expected.length).setValues([expected]);
  }
}

function ensureSheetCapacity_(sheet, requiredRows) {
  const currentRows = sheet.getMaxRows();
  if (requiredRows > currentRows) {
    sheet.insertRowsAfter(currentRows, requiredRows - currentRows);
  }
}

function contractToSheetRow_(contract) {
  const projectCodes = Array.isArray(contract.project_codes)
    ? contract.project_codes.join(', ')
    : '';

  return [
    safeCell_(contract.contract_id),
    safeCell_(contract.legacy_id),
    safeCell_(contract.contract_code),
    safeCell_(contract.contract_name),
    safeCell_(contract.project_id),
    safeCell_(contract.project_code),
    safeCell_(contract.project_name),
    projectCodes,
    safeCell_(contract.start_date),
    safeCell_(contract.end_date),
    numericCell_(contract.amount),
    safeCell_(contract.status),
    safeCell_(contract.kind),
    safeCell_(contract.division),
    safeCell_(contract.client_id),
    safeCell_(contract.client_name),
    safeCell_(contract.sub_client_id),
    safeCell_(contract.sub_client_name),
    safeCell_(contract.org_unit_id),
    safeCell_(contract.org_unit_name),
    safeCell_(contract.description),
    jsonCell_(contract.ext),
    safeCell_(contract.created_at),
    safeCell_(contract.updated_at),
    jsonCell_(contract.projects),
  ];
}

function safeCell_(value) {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  return value;
}

function numericCell_(value) {
  if (value === null || value === undefined || value === '') {
    return '';
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : String(value);
}

function jsonCell_(value) {
  if (value === null || value === undefined) {
    return '';
  }
  return JSON.stringify(value);
}
