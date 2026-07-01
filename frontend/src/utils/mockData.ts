export const globalMock = {
    "base_ym": "202402",
    "total_companies": 14000,
    "risk_companies": 3500,
    "grade_distribution": [
        {"Z_GRADE": "G1", "cnt": 5000},
        {"Z_GRADE": "G2", "cnt": 3500},
        {"Z_GRADE": "G3", "cnt": 2000},
        {"Z_GRADE": "G4", "cnt": 1500},
        {"Z_GRADE": "G5", "cnt": 2000}
    ],
    "top_risk_industries": [
        {"industry": "59", "total": 106, "risk_cnt": 69},
        {"industry": "41", "total": 400, "risk_cnt": 200},
        {"industry": "68", "total": 600, "risk_cnt": 250},
        {"industry": "13", "total": 357, "risk_cnt": 133},
        {"industry": "47", "total": 864, "risk_cnt": 319}
    ]
};

export const branchBorrowersMock = Array.from({length: 50}, (_, i) => ({
    V_BZNO: 1000000000 + i,
    STD_INDS_CFC: ["10", "41", "47", "59", "68"][i % 5],
    PROB_FULL: 0.9 - (i * 0.015),
    Z_SCORE: 1.5,
    Z_GRADE: ["G5", "G4", "G3", "G2", "G1"][Math.floor(i / 10)],
    OLD_PROB: [0, 3, 7].includes(i) ? 0.15 + (i * 0.01) : 0.82 - (i * 0.013),
    NICE_GRADE_CUR: [0, 3, 7].includes(i) ? "A-" : ["B-", "B", "BB-", "BB", "BB+"][Math.floor(i / 10)],
    NICE_GRADE_PREV: [0, 3, 7].includes(i) ? "A" : ["B", "B", "BB", "BB", "BBB-"][Math.floor(i / 10)],
    KIS_GRADE_CUR: [0, 3, 7].includes(i) ? "A-" : ["C", "CC", "CCC", "B-", "B"][Math.floor(i / 10)],
    KIS_GRADE_PREV: [0, 3, 7].includes(i) ? "A" : ["CC", "CC", "B-", "B", "B+"][Math.floor(i / 10)]
}));

export const borrowerDetailMock = {
    V_BZNO: "1000000000",
    STD_INDS_CFC: "59",
    PROB_FULL: 0.85,
    Z_GRADE: "G5",
    "여신수출금액": 1500000000,
    "내수금액": 1400000000,
    "총매출금액": 2900000000,
    "종업원수": 150,
    "총자산": 5000000000,
    "자본총계": 1500000000,
    "매출액": 2900000000,
    "영업이익": -120000000,
    "KIS 점수": 45,
    "NICE등급코드": "B-",
    "신용평가모형구분코드": "C101",
    "기업평가의견": "부정적",
    "신용등급": "B-",
    BASE_YM: "202402"
};

export const aiTipsMock = {
    summary: "본 차주는 최근 6개월 내 대출 잔액이 급증하였으며, 산업 전망(정보통신업) 대비 매출 성장세가 둔화되어 부도 위험이 매우 높습니다(85%).",
    tips: [
        "신규 여신 한도 축소 및 만기 연장 심사 강화 (우선 회수 전략 수립)",
        "담보물 가치 재평가 및 추가 담보 확보 방안 논의",
        "타 금융기관의 익스포저 변동 및 연체 이력 상시 모니터링 체계 가동"
    ]
};

export const shapMockData = [
  { name: 'Base PD', value: 15.0, fill: '#94a3b8' },
  { name: '매출 감소', value: 45.0, fill: '#ea580c' },
  { name: '연쇄 부도 우려', value: 25.0, fill: '#f59e0b' },
  { name: '단기차입 증가', value: 10.0, fill: '#fbbf24' },
  { name: '우량 담보', value: -10.0, fill: '#3b82f6' },
  { name: 'Final PD', value: 85.0, fill: '#1e293b' }
];

export const featureContributions = [
  { label: '경기 침체에 따른 매출 급감', value: 45.0, color: '#ea580c' },
  { label: '동종업계 연쇄 부도 우려', value: 25.0, color: '#f59e0b' },
  { label: '최근 단기 차입금 급증', value: 10.0, color: '#fbbf24' },
  { label: '우량 부동산 담보 보유', value: -10.0, color: '#3b82f6' },
];

export const simulationMock = {
    impacted_industries: [
        { industry: "부동산업", risk_increase: 12.5 },
        { industry: "건설업", risk_increase: 10.2 },
        { industry: "숙박 및 음식점업", risk_increase: 8.4 },
        { industry: "도매 및 소매업", risk_increase: 5.1 },
        { industry: "정보통신업", risk_increase: 3.2 }
    ]
};
