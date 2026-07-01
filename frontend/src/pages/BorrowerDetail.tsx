import { useEffect, useState } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { AlertOctagon, ArrowLeft, Bot, Info, Calculator, TrendingUp, CheckCircle, Activity, AlertTriangle, BarChart2, List } from 'lucide-react';
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Tooltip as RechartsTooltip, AreaChart, Area, CartesianGrid, XAxis, YAxis, Legend, BarChart, Bar, Cell } from 'recharts';
import { borrowerDetailMock, shapMockData, featureContributions } from '../utils/mockData';
import { getIndustryName } from '../utils/industry';
import { API_BASE_URL } from '../config';

const radarMockData = {
    target: {"활동성": 30, "수익성": 10, "안정성": 20, "성장성": 25, "규모": 60},
    industry_avg: {"활동성": 50, "수익성": 45, "안정성": 55, "성장성": 40, "규모": 50}
};

const tsMockData = [
    { month: '23.09', pd: 0.12 },
    { month: '23.10', pd: 0.15 },
    { month: '23.11', pd: 0.28 },
    { month: '23.12', pd: 0.45 },
    { month: '24.01', pd: 0.72 },
    { month: '24.02', pd: 0.85 }
];

export default function BorrowerDetail() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const baseYm = searchParams.get('base_ym');
  const navigate = useNavigate();
  const [data, setData] = useState<any>(null);
  const [useRealData, setUseRealData] = useState(true);
  const [aiTips, setAiTips] = useState<{ text: string; loading: boolean; error: string | null }>({ text: '', loading: false, error: null });

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
    if (!data) return;
    setAiTips({ text: '', loading: true, error: null });
    fetch(`${API_BASE_URL}/api/ai/tips`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        borrower_data: {
          industry: getIndustryName(data.STD_INDS_CFC),
          business_age_months: data.BUSINESS_AGE,
          default_probability: data.PROB_FULL,
          erm_grade: data.Z_GRADE,
        },
      }),
    })
      .then(res => res.ok ? res.json() : res.json().then(err => Promise.reject(err)))
      .then(result => setAiTips({ text: result.tips, loading: false, error: null }))
      .catch(err => setAiTips({ text: '', loading: false, error: err?.detail || 'AI 팁을 불러오지 못했습니다.' }));
  }, [data?.V_BZNO]);

  if (!data) return <div className="p-6">Loading Details...</div>;

  const isAiHighRisk = data.PROB_FULL > 0.5;
  const isExistingHighRisk = ['G4', 'G5'].includes(data.Z_GRADE);
  
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
  const radarData = Object.keys(radarMockData.target).map(key => ({
    subject: key,
    A: radarMockData.target[key as keyof typeof radarMockData.target],
    B: radarMockData.industry_avg[key as keyof typeof radarMockData.industry_avg]
  }));

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

      <div className="grid-2" style={{alignItems: 'stretch', gap: '24px'}}>
        {/* Row 1 */}
        {/* 1. 기업 개요 */}
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <Info size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>기업 개요</h2>
          </div>
          <div className="card grid-2" style={{flex: 1, alignContent: 'center'}}>
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
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
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

        {/* Row 2 */}
        {/* 3. 주요 재무/비재무 스냅샷 */}
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <Calculator size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>주요 재무/비재무 스냅샷</h2>
          </div>
          <div className="card flex-col" style={{gap: '16px', flex: 1, justifyContent: 'center'}}>
            <div className="flex-row" style={{justifyContent: 'space-between', borderBottom: '1px dashed var(--border)', paddingBottom: '12px'}}>
              <span className="font-regular" style={{color: 'var(--text-muted)'}}>자본총계</span>
              <span className="font-bold">{data['자본총계']?.toLocaleString() ?? 'N/A'} 천원</span>
            </div>
            <div className="flex-row" style={{justifyContent: 'space-between', borderBottom: '1px dashed var(--border)', paddingBottom: '12px'}}>
              <span className="font-regular" style={{color: 'var(--text-muted)'}}>총자산</span>
              <span className="font-bold">{data['총자산']?.toLocaleString() ?? 'N/A'} 천원</span>
            </div>
            <div className="flex-row" style={{justifyContent: 'space-between', borderBottom: '1px dashed var(--border)', paddingBottom: '12px'}}>
              <span className="font-regular" style={{color: 'var(--text-muted)'}}>매출액</span>
              <span className="font-bold">{data['매출액']?.toLocaleString() ?? 'N/A'} 천원</span>
            </div>
            <div className="flex-row" style={{justifyContent: 'space-between', borderBottom: '1px dashed var(--border)', paddingBottom: '12px'}}>
              <span className="font-regular" style={{color: 'var(--text-muted)'}}>KIS 점수</span>
              <span className="font-bold">{data['CG01_KIS_SCORE'] === -1 ? '등급 없음 (초고위험)' : data['CG01_KIS_SCORE']}</span>
            </div>
            <div className="flex-row" style={{justifyContent: 'space-between'}}>
              <span className="font-regular" style={{color: 'var(--text-muted)'}}>NICE 등급</span>
              <span className="font-bold">{data['NICE_GRADE_CUR']}</span>
            </div>
          </div>
        </div>

        {/* 4. 부도 확률 시계열 추이 추정 */}
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <Activity size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>부도 확률 시계열 추이 추정</h2>
          </div>
          <div className="card" style={{flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
            <div style={{width: '100%', height: '240px'}}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={tsMockData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
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

        {/* Row 3 */}
        {/* 5. 기업 역량 진단 (Radar) */}
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <TrendingUp size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>기업 역량 진단 (Radar)</h2>
          </div>
          <div className="card" style={{flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
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
          </div>
        </div>

        {/* 6. 핵심 리스크 및 대응 방안 (NEW) */}
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <AlertTriangle size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>핵심 리스크 및 대응 방안</h2>
          </div>
          <div className="card flex-col" style={{flex: 1, gap: '16px', justifyContent: 'center'}}>
            {aiTips.loading && (
              <p className="font-regular" style={{color: 'var(--text-muted)', fontSize: '14px'}}>Gemini가 분석 의견을 생성 중입니다...</p>
            )}
            {aiTips.error && (
              <p className="font-regular" style={{color: 'var(--danger)', fontSize: '14px'}}>{aiTips.error}</p>
            )}
            {!aiTips.loading && !aiTips.error && aiTips.text && (
              <p className="font-regular" style={{color: 'var(--text-main)', lineHeight: 1.6, fontSize: '14px', whiteSpace: 'pre-wrap'}}>
                {aiTips.text}
              </p>
            )}
          </div>
        </div>

        {/* Row 4 */}
        {/* 7. 요인별 기여도 시각화 (SHAP) */}
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <BarChart2 size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>요인별 기여도 시각화 (SHAP)</h2>
          </div>
          <div className="card" style={{flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
            <div style={{width: '100%', height: '260px'}}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={shapMockData} layout="vertical" margin={{ top: 20, right: 30, left: 10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={true} vertical={false} stroke="#e5e7eb" />
                  <XAxis type="number" tick={{fill: 'var(--text-muted)', fontSize: 12}} domain={[-20, 100]} />
                  <YAxis dataKey="name" type="category" tick={{fill: 'var(--text-main)', fontSize: 12, fontWeight: 600}} width={90} />
                  <RechartsTooltip cursor={{fill: 'rgba(0,0,0,0.05)'}} contentStyle={{backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)', borderRadius: '8px'}} />
                  <Bar dataKey="value" radius={4} barSize={20}>
                    {shapMockData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* 8. 변수별 위험 기여량 상세 */}
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <List size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>변수별 위험 기여량 상세</h2>
          </div>
          <div className="card flex-col" style={{flex: 1, gap: '24px', justifyContent: 'center'}}>
            {featureContributions.map((feat, idx) => {
              const percentWidth = Math.abs(feat.value) / 50 * 100;
              
              return (
                <div key={idx} className="flex-col" style={{gap: '10px'}}>
                  <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'flex-end'}}>
                    <span className="font-bold" style={{color: 'var(--text-main)', fontSize: '15px'}}>{feat.label}</span>
                    <span className="font-extrabold" style={{color: feat.color, fontSize: '16px'}}>
                      {feat.value > 0 ? '+' : ''}{feat.value.toFixed(1)}%p
                    </span>
                  </div>
                  <div style={{width: '100%', height: '8px', backgroundColor: 'var(--bg-main)', borderRadius: '4px', overflow: 'hidden'}}>
                    <div style={{width: `${Math.min(percentWidth, 100)}%`, height: '100%', backgroundColor: feat.color, borderRadius: '4px'}} />
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
