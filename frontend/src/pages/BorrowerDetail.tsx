import { useEffect, useState } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { AlertOctagon, ArrowLeft, Bot, Info, Calculator, TrendingUp, CheckCircle, Activity, AlertTriangle, BarChart2, List, ChevronDown } from 'lucide-react';
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Tooltip as RechartsTooltip, AreaChart, Area, CartesianGrid, XAxis, YAxis, Legend, BarChart, Bar, Cell } from 'recharts';
import { borrowerDetailMock } from '../utils/mockData';
import { getIndustryName } from '../utils/industry';
import { API_BASE_URL } from '../config';

// AI 분석 API 호출 실패 시 등급 기준 일반 관리 가이드로 대체하는 fallback 팁
const FALLBACK_TIPS_HIGH_RISK = [
  { title: '신규 여신 취급 전 면밀 검토 및 담보 확보', reason: '고위험 등급(G4/G5) 차주는 추가 익스포저 확대 전 보수적인 심사와 충분한 담보/보증 확보가 필요합니다.' },
  { title: '현금흐름 및 연체 현황 밀착 모니터링', reason: '부실 징후를 조기에 포착하기 위해 월 단위로 재무 상태와 상환 이력을 점검하는 것이 중요합니다.' },
  { title: '채권 보전 조치 사전 검토', reason: '리스크가 현실화될 경우를 대비해 담보 설정 현황과 회수 방안을 미리 점검해 두어야 합니다.' },
];
const FALLBACK_TIPS_NORMAL = [
  { title: '정기적인 재무/비재무 현황 점검', reason: '안정권 차주라도 분기별 재무제표 및 영업 현황을 주기적으로 확인해 변화를 조기에 파악해야 합니다.' },
  { title: '업종 평균 대비 경쟁력 모니터링', reason: '동일 업종 내 상대적 위치를 파악하여 잠재적 리스크 요인을 선제적으로 관리합니다.' },
  { title: '추가 거래 확대 가능성 검토', reason: '안정적인 차주는 장기적인 관계 강화를 위해 맞춤형 금융 상품 제안을 검토할 수 있습니다.' },
];

export default function BorrowerDetail({ baseYm: globalBaseYm }: { baseYm?: string } = {}) {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  // 상단 헤더의 기준일 선택(전역 상태)이 이 페이지에도 실시간으로 반영되어야
  // 하므로, URL의 최초 진입 시점 스냅샷(base_ym)보다 우선한다.
  const baseYm = globalBaseYm || searchParams.get('base_ym') || undefined;
  const navigate = useNavigate();
  const [data, setData] = useState<any>(null);
  const [useRealData, setUseRealData] = useState(true);
  const [aiTips, setAiTips] = useState<{ summary: string; tips: { title: string; reason: string }[]; loading: boolean; isFallback: boolean }>({ summary: '', tips: [], loading: false, isFallback: false });
  const [expandedTip, setExpandedTip] = useState<number | null>(null);
  const [financials, setFinancials] = useState<any[]>([]);
  const [pdHistory, setPdHistory] = useState<{ month: string; pd: number }[]>([]);
  const [shapData, setShapData] = useState<{ base_pd: number; final_pd: number; features: { feature: string; label: string; shap_raw: number; impact_score: number }[] } | null>(null);
  const [capability, setCapability] = useState<{ target: Record<string, number>; industry_avg: Record<string, number>; peer_count: number } | null>(null);

  useEffect(() => {
    setData(null);
    if (useRealData && id) {
      const url = baseYm
        ? `${API_BASE_URL}/api/borrowers/${id}?base_ym=${baseYm}`
        : `${API_BASE_URL}/api/borrowers/${id}`;
      fetch(url)
        .then(res => res.ok ? res.json() : Promise.reject(res))
        .then(real => {
          if (real && !real.error) {
            const merged = {
              ...borrowerDetailMock,
              ...real,
              company_name: `기업_${real.V_BZNO || id}`,
              company_id: String(real.V_BZNO || id),
              PROB_FULL: real.PROB_FULL || 0.05,
              Z_GRADE: real.Z_GRADE || 'G2',
              industry: getIndustryName(real.STD_INDS_CFC) || "제조업",
            };
            setData(merged);
          } else {
            setData({ ...borrowerDetailMock, V_BZNO: id || borrowerDetailMock.V_BZNO });
          }
        })
        .catch(() => {
          setData({ ...borrowerDetailMock, V_BZNO: id || borrowerDetailMock.V_BZNO });
        });
    } else {
      setTimeout(() => {
        setData({ ...borrowerDetailMock, V_BZNO: id || borrowerDetailMock.V_BZNO });
      }, 200);
    }
  }, [id, useRealData, baseYm]);

  useEffect(() => {
    if (!useRealData || !id) {
      setFinancials([]);
      return;
    }
    const url = baseYm
      ? `${API_BASE_URL}/api/borrowers/${id}/financials?base_ym=${baseYm}`
      : `${API_BASE_URL}/api/borrowers/${id}/financials`;
    fetch(url)
      .then(res => res.ok ? res.json() : Promise.reject(res))
      .then(rows => setFinancials(Array.isArray(rows) ? rows : []))
      .catch(() => setFinancials([]));
  }, [id, useRealData, baseYm]);

  useEffect(() => {
    if (!useRealData || !id) {
      setPdHistory([]);
      return;
    }
    const url = baseYm
      ? `${API_BASE_URL}/api/borrowers/${id}/pd_history?base_ym=${baseYm}&months=6`
      : `${API_BASE_URL}/api/borrowers/${id}/pd_history?months=6`;
    fetch(url)
      .then(res => res.ok ? res.json() : Promise.reject(res))
      .then(rows => setPdHistory(Array.isArray(rows) ? rows : []))
      .catch(() => setPdHistory([]));
  }, [id, useRealData, baseYm]);

  useEffect(() => {
    if (!useRealData || !id) {
      setShapData(null);
      return;
    }
    const url = baseYm
      ? `${API_BASE_URL}/api/borrowers/${id}/shap?base_ym=${baseYm}`
      : `${API_BASE_URL}/api/borrowers/${id}/shap`;
    fetch(url)
      .then(res => res.ok ? res.json() : Promise.reject(res))
      .then(result => setShapData(result))
      .catch(() => setShapData(null));
  }, [id, useRealData, baseYm]);

  useEffect(() => {
    if (!useRealData || !id) {
      setCapability(null);
      return;
    }
    const url = baseYm
      ? `${API_BASE_URL}/api/borrowers/${id}/capability?base_ym=${baseYm}`
      : `${API_BASE_URL}/api/borrowers/${id}/capability`;
    fetch(url)
      .then(res => res.ok ? res.json() : Promise.reject(res))
      .then(result => setCapability(result))
      .catch(() => setCapability(null));
  }, [id, useRealData, baseYm]);

  useEffect(() => {
    if (!data) return;
    setExpandedTip(null);
    setAiTips({ summary: '', tips: [], loading: true, isFallback: false });
    fetch(`${API_BASE_URL}/api/ai/tips`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bzno: String(data.V_BZNO),
        base_ym: String(data.BASE_YM),
        borrower_data: {
          industry: getIndustryName(data.STD_INDS_CFC),
          business_age_months: data.BUSINESS_AGE,
          default_probability: data.PROB_FULL,
          erm_grade: data.Z_GRADE,
        },
      }),
    })
      .then(res => res.ok ? res.json() : res.json().then(err => Promise.reject(err)))
      .then(result => setAiTips({ summary: result.summary, tips: result.tips || [], loading: false, isFallback: false }))
      .catch(() => {
        const isHighRisk = ['G4', 'G5'].includes(data.Z_GRADE);
        setAiTips({
          summary: '⏳ 현재 실시간 AI 분석 요청이 몰려 지연되고 있습니다. 잠시 후 다시 시도해 주세요. 아래는 등급 기준 일반 관리 가이드입니다.',
          tips: isHighRisk ? FALLBACK_TIPS_HIGH_RISK : FALLBACK_TIPS_NORMAL,
          loading: false,
          isFallback: true,
        });
      });
  }, [data?.V_BZNO, data?.BASE_YM]);

  if (!data) return <div className="p-6">Loading Details...</div>;

  const isAiHighRisk = data.PROB_FULL > 0.5;
  // Z_GRADE는 ERM 자체 등급이라 이걸로 "기존"을 판정하면 ERM을 ERM과 비교하는 셈이 된다.
  // 실제 은행 내부 조기경보 관찰등급(OBV_ELYWRN_OBV_GRD_DSC, B=위험)을 기준으로 판정한다.
  const isExistingHighRisk = data.OBV_ELYWRN_OBV_GRD_DSC === 'B';
  
  // 기존신용평가 등급(NICE_GRADE_CUR)과 OLD_PROB은 백엔드가 실측 PROB_FULL 분포
  // 기반 grade_mapping.py로 산출해 내려주므로 그대로 사용한다.
  const getLegacyGrade = (_grade: string) => data.NICE_GRADE_CUR || _grade;

  const getLegacyPd = (_prob: number, _grade: string) => (data.OLD_PROB * 100).toFixed(2);

  const ERM_GRADE_LABELS: Record<string, string> = {
    'G1': 'G1 (최우량)',
    'G2': 'G2 (안정권)',
    'G3': 'G3 (주의요망)',
    'G4': 'G4 (고위험)',
    'G5': 'G5 (부실우려)',
  };

  const getErmGrade = (_prob: number) => {
    return ERM_GRADE_LABELS[data.Z_GRADE] || data.Z_GRADE;
  };

  const getAnalysisStatus = () => {
    if (isAiHighRisk && !isExistingHighRisk) return 'BLIND_SPOT';
    if (isAiHighRisk && isExistingHighRisk) return 'HIGH_RISK';
    return 'SAFE';
  };
  const status = getAnalysisStatus();
  const radarData = capability
    ? Object.keys(capability.target).map(key => ({
        subject: key,
        A: capability.target[key],
        B: capability.industry_avg[key],
      }))
    : [];

  return (
    <div className="flex-col" style={{gap: '24px'}}>
      <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
        <button onClick={() => navigate(-1)} className="btn btn-ghost" style={{padding: '8px 16px', minHeight: 'auto'}}>
          <ArrowLeft size={18} /> 뒤로가기
        </button>
        <button 
          onClick={() => setUseRealData(!useRealData)}
          style={{
            padding: '6px 14px',
            borderRadius: '20px',
            border: 'none',
            backgroundColor: useRealData ? '#10b981' : '#64748b',
            color: 'white',
            fontWeight: 700,
            fontSize: '13px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            boxShadow: '0 2px 6px rgba(0,0,0,0.1)'
          }}
        >
          {useRealData ? '🔌 실데이터 연동 중 (DuckDB)' : '🧪 목업 모드 (테스트)'}
        </button>
      </div>

      <div className="flex-row" style={{justifyContent: 'space-between', marginBottom: '8px'}}>
        <div className="flex-row" style={{gap: '12px', alignItems: 'center'}}>
          <h1 className="font-bold">기업_{data.V_BZNO} <span className="font-medium" style={{fontSize: '20px', color: 'var(--text-muted)'}}>({data.V_BZNO})</span></h1>
          <span className="badge" style={{fontSize: '13px', padding: '6px 14px', backgroundColor: '#f1f5f9', color: '#475569', border: '1px solid #cbd5e1', fontWeight: 700}}>
            🏛️ 기존신용평가 등급: {getLegacyGrade(data.Z_GRADE)}
          </span>
          <span className="badge" style={{fontSize: '13px', padding: '6px 14px', fontWeight: 800, backgroundColor: ['G4 (고위험)', 'G5 (부실우려)'].includes(getErmGrade(data.PROB_FULL)) ? '#fee2e2' : ['G3 (주의요망)'].includes(getErmGrade(data.PROB_FULL)) ? '#fef3c7' : '#d1fae5', color: ['G4 (고위험)', 'G5 (부실우려)'].includes(getErmGrade(data.PROB_FULL)) ? '#dc2626' : ['G3 (주의요망)'].includes(getErmGrade(data.PROB_FULL)) ? '#d97706' : '#059669', border: 'none'}}>
            ⚡ ERM 등급: {getErmGrade(data.PROB_FULL)}
          </span>
        </div>
        <button className="btn btn-primary">
          상세 보고서 출력
        </button>
      </div>

      <div className="flex-col" style={{gap: '24px'}}>
        {/* Row 1 (1열 세로 배치): 1. 기업 개요 */}
        <div className="flex-col" style={{gap: '12px'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <Info size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>기업 개요</h2>
          </div>
          <div className="card grid-4">
            <div className="flex-col" style={{gap: '8px'}}>
              <span className="font-regular" style={{color: 'var(--text-muted)'}}>업종</span>
              <span className="font-bold" style={{fontSize: '16px'}}>{getIndustryName(data.STD_INDS_CFC)}</span>
            </div>
            <div className="flex-col" style={{gap: '8px'}}>
              <span className="font-regular" style={{color: 'var(--text-muted)'}}>기준년월</span>
              <span className="font-bold" style={{fontSize: '16px'}}>{data.BASE_YM}</span>
            </div>
            <div className="flex-col" style={{gap: '8px'}}>
              <span className="font-regular" style={{color: 'var(--text-muted)'}}>관할 지점</span>
              <span className="font-bold" style={{fontSize: '16px'}}>{data.V_BRANCH_CODE}</span>
            </div>
            <div className="flex-col" style={{gap: '8px'}}>
              <span className="font-regular" style={{color: 'var(--text-muted)'}}>업력 (개월)</span>
              <span className="font-bold" style={{fontSize: '16px'}}>{Math.round(data.BUSINESS_AGE)}</span>
            </div>
          </div>
        </div>

        {/* 2. AI 조기경보 모델 분석 의견 */}
        <div className="flex-col" style={{gap: '12px'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <Bot size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>AI 조기경보 모델 분석 의견</h2>
          </div>
          <div className={`card ${status !== 'SAFE' ? 'card-danger' : 'card-safe'} flex-col`} style={{gap: '16px', flex: 1, justifyContent: 'center'}}>
            {/* 4-Metric Comparison Dashboard Box */}
            <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', background: 'white', padding: '16px 18px', borderRadius: '10px', border: '1px solid var(--border)', boxShadow: '0 2px 8px rgba(0,0,0,0.03)'}}>
              <div className="flex-col" style={{gap: '8px', borderRight: '1px solid #e2e8f0', paddingRight: '16px'}}>
                <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
                  <span style={{fontSize: '13px', color: 'var(--text-muted)', fontWeight: 700}}>🏛️ 기존신용평가모형 (Legacy)</span>
                  <span className="badge" style={{backgroundColor: '#f1f5f9', color: '#475569', fontSize: '11px', fontWeight: 700}}>{getLegacyGrade(data.Z_GRADE)}</span>
                </div>
                <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'baseline'}}>
                  <span style={{fontSize: '13px', color: 'var(--text-main)', fontWeight: 600}}>기존모델 부도확률</span>
                  <span style={{fontSize: '20px', fontWeight: 800, color: '#64748b'}}>{getLegacyPd(data.PROB_FULL, data.Z_GRADE)}%</span>
                </div>
              </div>

              <div className="flex-col" style={{gap: '8px', paddingLeft: '6px'}}>
                <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
                  <span style={{fontSize: '13px', color: 'var(--primary)', fontWeight: 800}}>⚡ AI ERM 신용평가모형 (New)</span>
                  <span className="badge badge-primary" style={{padding: '2px 8px', fontSize: '11px', fontWeight: 800, backgroundColor: ['G4 (고위험)','G5 (부실우려)'].includes(getErmGrade(data.PROB_FULL)) ? '#fee2e2' : ['G3 (주의요망)'].includes(getErmGrade(data.PROB_FULL)) ? '#fef3c7' : '#d1fae5', color: ['G4 (고위험)','G5 (부실우려)'].includes(getErmGrade(data.PROB_FULL)) ? '#dc2626' : ['G3 (주의요망)'].includes(getErmGrade(data.PROB_FULL)) ? '#d97706' : '#059669', border: 'none'}}>{getErmGrade(data.PROB_FULL)}</span>
                </div>
                <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'baseline'}}>
                  <span style={{fontSize: '13px', color: 'var(--text-main)', fontWeight: 700}}>ERM 산출 부도확률</span>
                  <span style={{fontSize: '24px', fontWeight: 900, color: data.PROB_FULL >= 0.3 ? 'var(--danger)' : data.PROB_FULL >= 0.1 ? 'var(--warning)' : 'var(--safe)'}}>
                    {(data.PROB_FULL * 100).toFixed(2)}%
                  </span>
                </div>
              </div>
            </div>

            {status === 'BLIND_SPOT' && (
              <div style={{backgroundColor: '#fef2f2', borderRadius: '8px', padding: '16px', display: 'flex', gap: '12px', alignItems: 'flex-start'}}>
                <AlertOctagon size={24} color="var(--danger)" style={{flexShrink: 0}} />
                <div className="flex-col" style={{gap: '4px'}}>
                  <span className="font-bold" style={{color: '#b91c1c', fontSize: '15px'}}>잠재 리스크 감지 (사각지대)</span>
                  <span className="font-regular" style={{color: '#991b1b', fontSize: '14px', lineHeight: 1.5}}>
                    기존 은행 리스크 지표는 {getLegacyGrade(data.Z_GRADE)}로 상대적으로 안전한 편이나, AI 모델은 해당 차주의 부도 확률을 고위험 수준인 {(data.PROB_FULL * 100).toFixed(2)}% (ERM 등급: {getErmGrade(data.PROB_FULL)})로 예측했습니다. 숨겨진 부실 요인이 없는지 선제적 여신 관리가 필요합니다.
                  </span>
                </div>
              </div>
            )}
            
            {status === 'HIGH_RISK' && (
              <div style={{backgroundColor: '#fef2f2', borderRadius: '8px', padding: '16px', display: 'flex', gap: '12px', alignItems: 'flex-start'}}>
                <AlertOctagon size={24} color="var(--danger)" style={{flexShrink: 0}} />
                <div className="flex-col" style={{gap: '4px'}}>
                  <span className="font-bold" style={{color: '#b91c1c', fontSize: '15px'}}>초고위험 경고 (부도 임박)</span>
                  <span className="font-regular" style={{color: '#991b1b', fontSize: '14px', lineHeight: 1.5}}>
                    AI 예측 부도 확률이 {(data.PROB_FULL * 100).toFixed(2)}% (ERM 등급: {getErmGrade(data.PROB_FULL)})로 매우 높습니다. 기존 지표({getLegacyGrade(data.Z_GRADE)})에서도 이미 위험이 감지되었으며, 즉각적인 채권 보전 조치 및 모니터링 강화가 시급합니다.
                  </span>
                </div>
              </div>
            )}

            {status === 'SAFE' && (
              <div style={{backgroundColor: '#ecfdf5', borderRadius: '8px', padding: '16px', display: 'flex', gap: '12px', alignItems: 'flex-start'}}>
                <CheckCircle size={24} color="var(--safe)" style={{flexShrink: 0}} />
                <div className="flex-col" style={{gap: '4px'}}>
                  <span className="font-bold" style={{color: '#047857', fontSize: '15px'}}>정상 수준</span>
                  <span className="font-regular" style={{color: '#065f46', fontSize: '14px', lineHeight: 1.5}}>
                    AI 예측 부도 확률이 안전한 수준({(data.PROB_FULL * 100).toFixed(2)}%)입니다. 전반적으로 안정적인 재무 상태 및 영업 활동을 유지하고 있습니다.
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>

      </div>

      <div className="grid-2" style={{alignItems: 'stretch', gap: '24px'}}>
        {/* Row 2: 3. 주요 재무/비재무 (실측 3개년 추이) */}
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <Calculator size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>주요 재무/비재무 (최근 {financials.length || 3}개년)</h2>
          </div>
          <div className="card" style={{flex: 1, overflowX: 'auto'}}>
            {financials.length === 0 ? (
              <span className="font-regular" style={{color: 'var(--text-muted)'}}>재무 데이터를 불러오는 중입니다...</span>
            ) : (
              <table style={{width: '100%', fontSize: '13px'}}>
                <thead>
                  <tr>
                    <th style={{textAlign: 'left', paddingBottom: '8px', color: 'var(--text-muted)', fontWeight: 600}}>항목</th>
                    {financials.map(f => (
                      <th key={f.year} style={{textAlign: 'right', paddingBottom: '8px', color: 'var(--text-muted)', fontWeight: 600}}>{f.year}년</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[
                    { label: '자본총계', key: 'capital', unit: '천원' },
                    { label: '총자산', key: 'total_assets', unit: '천원' },
                    { label: '매출액', key: 'revenue', unit: '천원' },
                    { label: '영업이익', key: 'operating_profit', unit: '천원' },
                    { label: 'KIS 점수', key: 'kis_score', unit: '' },
                    { label: 'NICE 등급', key: 'nice_grade', unit: '' },
                  ].map(row => (
                    <tr key={row.key} style={{borderTop: '1px dashed var(--border)'}}>
                      <td style={{padding: '10px 0', color: 'var(--text-muted)'}}>{row.label}</td>
                      {financials.map(f => (
                        <td key={f.year} style={{padding: '10px 0', textAlign: 'right', fontWeight: 700}}>
                          {row.key === 'kis_score' && f[row.key] === -1
                            ? '등급 없음'
                            : typeof f[row.key] === 'number'
                              ? `${f[row.key].toLocaleString()}${row.unit ? ' ' + row.unit : ''}`
                              : f[row.key]}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* 5. 기업 역량 진단 (Radar) */}
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px', alignItems: 'center', justifyContent: 'space-between'}}>
            <div className="flex-row" style={{gap: '8px', alignItems: 'center'}}>
              <TrendingUp size={20} color="var(--primary)" />
              <h2 className="font-semibold" style={{margin: 0}}>기업 역량 진단 (Radar)</h2>
            </div>
            {capability && (
              <span className="font-regular" style={{fontSize: '12px', color: 'var(--text-muted)'}}>
                동일 업종 {capability.peer_count.toLocaleString()}개사 대비 백분위
              </span>
            )}
          </div>
          <div className="card" style={{flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
            {!capability ? (
              <span className="font-regular" style={{color: 'var(--text-muted)', fontSize: '14px'}}>역량 진단 계산 중입니다...</span>
            ) : (
            <div style={{width: '100%', height: '260px'}}>
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart cx="50%" cy="50%" outerRadius="80%" data={radarData}>
                  <PolarGrid stroke="var(--border)" />
                  <PolarAngleAxis dataKey="subject" tick={{fill: 'var(--text-main)', fontSize: 12, fontWeight: 500}} />
                  <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
                  <Radar name="해당 기업" dataKey="A" stroke="var(--primary)" fill="var(--primary)" fillOpacity={0.5} />
                  <Radar name="업종 평균" dataKey="B" stroke="var(--secondary)" fill="var(--secondary)" fillOpacity={0.3} />
                  <RechartsTooltip contentStyle={{backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)', borderRadius: '8px'}} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
            )}
          </div>
        </div>

        {/* Row 3: 4. 부도 확률 시계열 추이 추정 */}
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <Activity size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>부도 확률 시계열 추이 추정 (최근 {pdHistory.length || 6}개월)</h2>
          </div>
          <div className="card" style={{flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
            <div style={{width: '100%', height: '240px'}}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={pdHistory} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorPd" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={isAiHighRisk ? "var(--danger)" : "var(--primary)"} stopOpacity={0.3}/>
                      <stop offset="95%" stopColor={isAiHighRisk ? "var(--danger)" : "var(--primary)"} stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                  <XAxis dataKey="month" tick={{fill: 'var(--text-muted)', fontSize: 12}} dy={10} axisLine={{stroke: '#e5e7eb'}} tickLine={false} />
                  <YAxis tick={{fill: 'var(--text-muted)', fontSize: 12}} axisLine={{stroke: '#e5e7eb'}} tickLine={false} />
                  <Legend verticalAlign="bottom" height={36} iconType="circle" wrapperStyle={{fontSize: '13px', fontWeight: 500}} />
                  <Area type="monotone" dataKey="pd" name="ERM 부도확률(%)" stroke={isAiHighRisk ? "var(--danger)" : "var(--primary)"} fillOpacity={1} fill="url(#colorPd)" strokeWidth={3} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* 6. AI 핵심 리스크 및 대응 방안 */}
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <AlertTriangle size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>AI 핵심 리스크 및 대응 방안</h2>
          </div>
          <div className="card flex-col" style={{flex: 1, gap: '16px', justifyContent: aiTips.tips.length ? 'flex-start' : 'center'}}>
            {aiTips.loading && (
              <p className="font-regular" style={{color: 'var(--text-muted)', fontSize: '14px'}}>Gemini가 분석 의견을 생성 중입니다...</p>
            )}
            {!aiTips.loading && aiTips.tips.length > 0 && (
              <>
                {aiTips.summary && (
                  aiTips.isFallback ? (
                    <div style={{backgroundColor: '#fffbeb', border: '1px solid #fde68a', borderRadius: '8px', padding: '12px 14px'}}>
                      <span className="font-regular" style={{color: '#92400e', lineHeight: 1.6, fontSize: '14px'}}>
                        {aiTips.summary}
                      </span>
                    </div>
                  ) : (
                    <p className="font-regular" style={{color: 'var(--text-main)', lineHeight: 1.6, fontSize: '14px'}}>
                      {aiTips.summary}
                    </p>
                  )
                )}
                <div className="flex-col" style={{gap: '10px'}}>
                  {aiTips.tips.map((tip, idx) => {
                    const isOpen = expandedTip === idx;
                    return (
                      <div
                        key={idx}
                        style={{
                          border: '1px solid var(--border)',
                          borderRadius: '8px',
                          backgroundColor: isOpen ? 'var(--bg-main)' : 'white',
                          overflow: 'hidden',
                        }}
                      >
                        <button
                          onClick={() => setExpandedTip(isOpen ? null : idx)}
                          style={{
                            width: '100%',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            gap: '10px',
                            padding: '12px 14px',
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            textAlign: 'left',
                          }}
                        >
                          <span className="flex-row" style={{gap: '10px', alignItems: 'center'}}>
                            <span
                              className="font-bold"
                              style={{
                                flexShrink: 0,
                                width: '22px',
                                height: '22px',
                                borderRadius: '50%',
                                backgroundColor: 'var(--primary)',
                                color: 'white',
                                fontSize: '12px',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                              }}
                            >
                              {idx + 1}
                            </span>
                            <span className="font-bold" style={{fontSize: '14px', color: 'var(--text-main)'}}>{tip.title}</span>
                          </span>
                          <ChevronDown size={16} color="var(--text-muted)" style={{flexShrink: 0, transform: isOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s'}} />
                        </button>
                        {isOpen && (
                          <div style={{padding: '0 14px 14px 46px'}}>
                            <span className="font-regular" style={{fontSize: '13px', color: 'var(--text-muted)', lineHeight: 1.5}}>{tip.reason}</span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        </div>

        {/* Row 4 */}
        {/* 7. 요인별 기여도 시각화 (SHAP) */}
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px', alignItems: 'center', justifyContent: 'space-between'}}>
            <div className="flex-row" style={{gap: '8px', alignItems: 'center'}}>
              <BarChart2 size={20} color="var(--primary)" />
              <h2 className="font-semibold" style={{margin: 0}}>요인별 기여도 시각화 (SHAP)</h2>
            </div>
            {shapData && (
              <span className="font-regular" style={{fontSize: '12px', color: 'var(--text-muted)'}}>
                평균 {shapData.base_pd}% → 이 기업 {shapData.final_pd}%
              </span>
            )}
          </div>
          <div className="card" style={{flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
            {!shapData ? (
              <span className="font-regular" style={{color: 'var(--text-muted)', fontSize: '14px'}}>SHAP 분석 계산 중입니다...</span>
            ) : (
              <div style={{width: '100%', height: '260px'}}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={shapData.features} layout="vertical" margin={{ top: 20, right: 30, left: 10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={true} vertical={false} stroke="#e5e7eb" />
                    <XAxis type="number" tick={{fill: 'var(--text-muted)', fontSize: 12}} domain={[-100, 100]} />
                    <YAxis dataKey="label" type="category" tick={{fill: 'var(--text-main)', fontSize: 12, fontWeight: 600}} width={110} />
                    <RechartsTooltip cursor={{fill: 'rgba(0,0,0,0.05)'}} contentStyle={{backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)', borderRadius: '8px'}} />
                    <Bar dataKey="impact_score" radius={4} barSize={16}>
                      {shapData.features.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.impact_score >= 0 ? 'var(--danger)' : 'var(--primary)'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>

        {/* 8. 변수별 위험 기여량 상세 */}
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <List size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>변수별 위험 기여량 상세</h2>
          </div>
          <div className="card flex-col" style={{flex: 1, gap: '24px', justifyContent: 'center'}}>
            {!shapData ? (
              <span className="font-regular" style={{color: 'var(--text-muted)', fontSize: '14px'}}>SHAP 분석 계산 중입니다...</span>
            ) : shapData.features.slice(0, 4).map((feat, idx) => {
              const percentWidth = Math.abs(feat.impact_score);
              const color = feat.impact_score >= 0 ? 'var(--danger)' : 'var(--primary)';

              return (
                <div key={idx} className="flex-col" style={{gap: '10px'}}>
                  <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'flex-end'}}>
                    <span className="font-bold" style={{color: 'var(--text-main)', fontSize: '15px'}}>{feat.label}</span>
                    <span className="font-extrabold" style={{color, fontSize: '16px'}}>
                      {feat.impact_score > 0 ? '+' : ''}{feat.impact_score.toFixed(1)}
                    </span>
                  </div>
                  <div style={{width: '100%', height: '8px', backgroundColor: 'var(--bg-main)', borderRadius: '4px', overflow: 'hidden'}}>
                    <div style={{width: `${Math.min(percentWidth, 100)}%`, height: '100%', backgroundColor: color, borderRadius: '4px'}} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
