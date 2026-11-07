/* State — 화면 전역 상태(설정 모델·설명·현재 탭 등) */
window.MR = window.MR || {};

MR.state = {
  MODEL: null,        // config.json (편집 중인 사본)
  DOCS: {},           // 키별 한국어 설명
  MODEL_PATH: '',
  TAB: 'config',
  STATUS: null,       // 마지막 /api/status
  RESTARTING: false,  // 재시작 진행 중(완료 시 배너 교체)
  LOGTIMER: null
};
