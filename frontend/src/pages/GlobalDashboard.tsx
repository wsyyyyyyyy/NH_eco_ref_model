import { useEffect, useState } from 'react';
import { BarChart, Bar, LineChart, Line, ScatterChart, Scatter, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, CartesianGrid, ReferenceArea, ZAxis, LabelList, Cell, Legend } from 'recharts';
import { AlertTriangle, CheckCircle, TrendingUp, Users, BarChart as BarChartIcon } from 'lucide-react';
import { getIndustryName } from '../utils/industry';
import { globalMock } from '../utils/mockData';
import { API_BASE_URL } from '../config';

const COLORS = ['#ef4444', '#f97316', '#8b5cf6', '#3b82f6', '#10b981', '#ec4899', '#06b6d4', '#eab308'];

const formatShortName = (name: string) => {
  if (!name) return '';
  if (name.includes('농업')) return '농·임·어업';
  if (name.includes('도매')) return '도소매업';
  if (name.includes('숙박')) return '숙박음식업';
  if (name.includes('전기')) return '전기가스업';
  if (name.includes('사업시설')) return '사업지원';
  if (name.includes('전문')) return '전문과학기술';
  if (name.includes('출판') || name.includes('정보통신')) return '정보통신업';
  if (name.includes('운수')) return '운수창고업';
  return name;
};

const CustomScatterLabel = (props: any) => {
  const { x, y, value, index } = props;
  if (typeof x !== 'number' || typeof y !== 'number') return null;
  // 인덱스에 따라 라벨을 상/하/좌/우로 지그재그 분산 배치하여 버블 및 글씨 간 겹침 완벽 방지
  const positions = [
    { dx: 0, dy: -20, anchor: 'middle' },
    { dx: 0, dy: 28, anchor: 'middle' },
    { dx: 24, dy: 4, anchor: 'start' },
    { dx: -24, dy: 4, anchor: 'end' },
    { dx: 18, dy: -18, anchor: 'start' },
    { dx: -18, dy: 22, anchor: 'end' },
    { dx: 0, dy: -32, anchor: 'middle' },
    { dx: 0, dy: 38, anchor: 'middle' }
  ];
  const pos = positions[index % positions.length];
  return (
    <text 
      x={x + pos.dx} 
      y={y + pos.dy} 
      textAnchor={pos.anchor as any} 
      fill="#0f172a" 
      fontSize={13} 
      fontWeight={800}
      style={{
        textShadow: '2px 0 0 #fff, -2px 0 0 #fff, 0 2px 0 #fff, 0 -2px 0 #fff, 1px 1px #fff, -1px -1px #fff, 1px -1px #fff, -1px 1px #fff',
        pointerEvents: 'none'
      }}
    >
      {value}
    </text>
  );
};

const TrendTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload || !payload.length) return null;
  const point = payload[0].payload;
  return (
    <div style={{backgroundColor: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '8px', padding: '10px 14px'}}>
      <p style={{fontWeight: 700, marginBottom: '6px'}}>{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} style={{color: p.color, margin: '2px 0'}}>{p.name} : {p.value != null ? `${p.value}%` : '-'}</p>
      ))}
      {point?.censored && (
        <p style={{color: 'var(--text-muted)', fontSize: '12px', marginTop: '6px', maxWidth: '200px'}}>
          ⓘ 아직 12개월 관측이 끝나지 않아 실질 부도율을 집계할 수 없는 구간입니다.
        </p>
      )}
    </div>
  );
};

const PredictionVenn = ({ pc }: { pc: any }) => {
  if (!pc) return null;
  const { both, erm_only, internal_only, neither, total, lead_time } = pc;
  return (
    <div className="flex-row" style={{gap: '32px', alignItems: 'center', flexWrap: 'wrap'}}>
      <svg width="360" height="230" viewBox="0 0 360 230">
        <rect x="10" y="10" width="340" height="210" rx="12" fill="#f8fafc" stroke="#e5e7eb" />
        <circle cx="150" cy="115" r="80" fill="var(--primary)" fillOpacity="0.28" stroke="var(--primary)" strokeWidth="2" />
        <circle cx="225" cy="115" r="60" fill="#fbbf24" fillOpacity="0.35" stroke="#f59e0b" strokeWidth="2" />
        <text x="110" y="80" textAnchor="middle" fontSize="12" fontWeight={700} fill="var(--primary)">ERM 모델만 포착</text>
        <text x="110" y="100" textAnchor="middle" fontSize="20" fontWeight={800} fill="var(--primary)">{erm_only}</text>
        <text x="196" y="115" textAnchor="middle" fontSize="11" fontWeight={700} fill="#78350f">둘 다</text>
        <text x="196" y="132" textAnchor="middle" fontSize="16" fontWeight={800} fill="#78350f">{both}</text>
        <text x="255" y="150" textAnchor="middle" fontSize="12" fontWeight={700} fill="#b45309">내부만 포착</text>
        <text x="255" y="170" textAnchor="middle" fontSize="20" fontWeight={800} fill="#b45309">{internal_only}</text>
        <text x="180" y="210" textAnchor="middle" fontSize="12" fontWeight={600} fill="var(--text-muted)">
          둘 다 놓침 {neither}개 · 실제 부도 기업 총 {total}개 (내부등급 이력 보유분)
        </text>
      </svg>
      <div className="flex-col" style={{gap: '10px', minWidth: '220px'}}>
        <div>
          <div className="font-semibold" style={{color: 'var(--text-muted)', fontSize: '13px'}}>평균 조기경보 리드타임</div>
          <div className="font-extrabold" style={{fontSize: '28px', color: 'var(--primary)'}}>
            {lead_time?.avg_months != null ? `+${lead_time.avg_months}개월` : '-'}
          </div>
        </div>
        <p style={{fontSize: '12px', color: 'var(--text-muted)', margin: 0, maxWidth: '260px'}}>
          내부등급이 A→B로 전환되는 시점이 관측된 {lead_time?.n}개사 기준, ERM이 내부등급 하향보다 평균 {lead_time?.avg_months}개월 먼저 고위험(G4/G5)으로 경고했습니다.
          (내부등급이 데이터 시작 시점부터 이미 'B'였던 {lead_time?.left_censored_excluded}개사는 하향 시점을 알 수 없어 이 평균에서 제외 — 여전히 "둘 다 포착"에는 포함됩니다.)
        </p>
      </div>
    </div>
  );
};

export default function GlobalDashboard({ baseYm = '202402' }: { baseYm?: string }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [useRealData, setUseRealData] = useState(true);
  const [trendData, setTrendData] = useState<any[] | null>(null);
  const [predictionComparison, setPredictionComparison] = useState<any>(null);

  useEffect(() => {
    if (!useRealData) {
      setTrendData(null);
      return;
    }
    fetch(`${API_BASE_URL}/api/dashboard/trend?base_ym=${baseYm}&months=6`)
      .then(res => res.json())
      .then(rows => setTrendData(Array.isArray(rows) ? rows : null))
      .catch(() => setTrendData(null));
  }, [baseYm, useRealData]);

  useEffect(() => {
    if (!useRealData) {
      setPredictionComparison(null);
      return;
    }
    fetch(`${API_BASE_URL}/api/dashboard/prediction_comparison`)
      .then(res => res.json())
      .then(setPredictionComparison)
      .catch(() => setPredictionComparison(null));
  }, [useRealData]);

  useEffect(() => {
    setLoading(true);
    if (useRealData) {
      fetch(`${API_BASE_URL}/api/dashboard/summary?base_ym=${baseYm}`)
        .then(res => res.json())
        .then(d => {
          if (d.top_risk_industries) {
            const grouped: Record<string, any> = {};
            d.top_risk_industries.forEach((ind: any) => {
              const name = getIndustryName(ind.industry);
              if (!grouped[name]) {
                grouped[name] = { industry: name, total: 0, risk_cnt: 0 };
              }
              grouped[name].total += ind.total;
              grouped[name].risk_cnt += ind.risk_cnt;
            });
            d.top_risk_industries = Object.values(grouped)
              .map((g: any) => ({
                ...g,
                risk_ratio: Number(((g.risk_cnt / g.total) * 100).toFixed(1))
              }))
              .sort((a: any, b: any) => b.risk_cnt - a.risk_cnt)
              .slice(0, 10);
          }
          setData(d);
          setLoading(false);
        })
        .catch(err => {
          console.error("Failed to fetch dashboard summary:", err);
          setLoading(false);
        });
    } else {
      setTimeout(() => {
          let d = JSON.parse(JSON.stringify(globalMock));
          if (baseYm === '202401') {
              d.total_companies = Math.floor(d.total_companies * 0.95);
              d.risk_companies = Math.floor(d.risk_companies * 0.92);
              d.grade_distribution.forEach((g: any) => g.cnt = Math.floor(g.cnt * 0.95));
          } else if (baseYm === '202312') {
              d.total_companies = Math.floor(d.total_companies * 0.90);
              d.risk_companies = Math.floor(d.risk_companies * 0.85);
              d.grade_distribution.forEach((g: any) => g.cnt = Math.floor(g.cnt * 0.90));
          }

          if (d.top_risk_industries) {
              const grouped: Record<string, any> = {};
              d.top_risk_industries.forEach((ind: any) => {
                  const name = getIndustryName(ind.industry);
                  if (!grouped[name]) {
                      grouped[name] = { industry: name, total: 0, risk_cnt: 0 };
                  }
                  grouped[name].total += ind.total;
                  grouped[name].risk_cnt += ind.risk_cnt;
              });
              d.top_risk_industries = Object.values(grouped)
                  .map((g: any) => ({
                      ...g,
                      risk_ratio: Number(((g.risk_cnt / g.total) * 100).toFixed(1))
                  }))
                  .sort((a: any, b: any) => b.risk_cnt - a.risk_cnt);
          }
          setData(d);
          setLoading(false);
      }, 200);
    }
  }, [baseYm, useRealData]);

  if (loading) return <div className="p-6">Loading Data...</div>;
  if (!data) return <div className="p-6">Error loading data.</div>;

  const safeCount = data.total_companies - data.risk_companies;
  const riskRatio = ((data.risk_companies / data.total_companies) * 100).toFixed(1);

  const lineChartData = trendData || [];
  const censoredMonths = lineChartData.filter((d: any) => d.censored);
  const firstCensoredMonth = censoredMonths[0]?.month;
  const lastMonth = lineChartData[lineChartData.length - 1]?.month;

  // 기준년월의 업종별 실제 고위험 비율과 기업수를 활용한 업종 리스크 매트릭스.
  // X축(기존 평가 위험도)은 legacy_risk_pct(OLD_PROB = PROB_FULL * 0.15 업종 평균) 실측값.
  const scatterData = (data.top_risk_industries || []).slice(0, 8).map((ind: any, idx: number) => {
    const shortName = formatShortName(ind.industry);
    const yVal = Number(ind.risk_ratio.toFixed(1));
    const xVal = Number((ind.legacy_risk_pct ?? 0).toFixed(2));
    return {
      name: shortName,
      fullName: ind.industry,
      x: Math.max(3.0, Math.min(24.0, xVal)), // X축 3~24% 범위 내 분산 배치
      y: yVal, // Y축 실제 ERM 고위험 비율
      z: Math.max(300, ind.total), // 버블 크기
      color: COLORS[idx % COLORS.length]
    };
  });

  return (
    <div className="flex-col" style={{gap: '24px'}}>
      <div className="flex-row" style={{justifyContent: 'space-between', marginBottom: '8px', alignItems: 'center'}}>
        <div className="flex-col" style={{gap: '8px'}}>
          <h1 className="font-bold">글로벌 뱅크 뷰</h1>
          <p className="font-regular">전체 은행 관점의 포트폴리오 리스크 요약 (기준일: {baseYm})</p>
        </div>
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

      {/* KPI Cards */}
      <div className="grid-3">
        <div className="card flex-col">
          <div className="flex-row" style={{gap: '8px', marginBottom: '16px'}}>
            <Users size={20} color="var(--primary)" />
            <span className="font-semibold" style={{color: 'var(--text-muted)'}}>전체 평가 기업 수</span>
          </div>
          <div className="flex-row" style={{alignItems: 'baseline', gap: '8px'}}>
            <div className="font-extrabold" style={{fontSize: '36px'}}>{data.total_companies.toLocaleString()}</div>
            <span className="font-medium" style={{color: 'var(--text-muted)'}}>개사</span>
          </div>
        </div>
        
        <div className="card card-danger flex-col">
          <div className="flex-row" style={{gap: '8px', marginBottom: '16px'}}>
            <AlertTriangle size={20} color="var(--danger)" />
            <span className="font-semibold" style={{color: 'var(--text-muted)'}}>고위험군 (G4, G5)</span>
          </div>
          <div className="flex-row" style={{alignItems: 'baseline', gap: '8px'}}>
            <div className="font-extrabold" style={{fontSize: '36px', color: 'var(--danger)'}}>{data.risk_companies.toLocaleString()}</div>
            <span className="font-medium">개사</span>
          </div>
          <p className="font-regular" style={{marginTop: '12px', fontSize: '14px'}}>전체 대비 {riskRatio}% 비중</p>
        </div>

        <div className="card card-safe flex-col">
          <div className="flex-row" style={{gap: '8px', marginBottom: '16px'}}>
            <CheckCircle size={20} color="var(--safe)" />
            <span className="font-semibold" style={{color: 'var(--text-muted)'}}>안전군 (G1, G2)</span>
          </div>
          <div className="flex-row" style={{alignItems: 'baseline', gap: '8px'}}>
            <div className="font-extrabold" style={{fontSize: '36px', color: 'var(--safe)'}}>{safeCount.toLocaleString()}</div>
            <span className="font-medium">개사</span>
          </div>
        </div>
      </div>

      <div className="grid-2">
        <div className="flex-col" style={{gap: '12px'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <TrendingUp size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>실질 부도율 vs 모델 예측력 비교 (PD-LAG)</h2>
          </div>
          <div className="card">
            <div style={{width: '100%', height: '300px'}}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={lineChartData} margin={{ top: 20, right: 30, left: -20, bottom: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                  {firstCensoredMonth && (
                    <ReferenceArea x1={firstCensoredMonth} x2={lastMonth} fill="#94a3b8" fillOpacity={0.08} />
                  )}
                  <XAxis dataKey="month" tick={{fill: 'var(--text-muted)', fontSize: 12}} dy={10} axisLine={{stroke: '#e5e7eb'}} tickLine={false} />
                  <YAxis tick={{fill: 'var(--text-muted)', fontSize: 12}} axisLine={{stroke: '#e5e7eb'}} tickLine={false} />
                  <RechartsTooltip content={<TrendTooltip />} />
                  <Legend verticalAlign="bottom" height={36} iconType="circle" wrapperStyle={{fontSize: '13px', fontWeight: 500, paddingTop: '16px'}} />
                  <Line type="monotone" dataKey="실제" name="시장 실질 부도율(%)" stroke="#94a3b8" strokeWidth={2} strokeDasharray="5 5" dot={{r:4, fill: '#fff', strokeWidth: 2}} connectNulls={false} />
                  <Line type="monotone" dataKey="기존" name="기존 모델 예측(%)" stroke="#fbbf24" strokeWidth={2} dot={{r:4}} />
                  <Line type="monotone" dataKey="신규" name="ERM 예측(%)" stroke="var(--primary)" strokeWidth={3} dot={{r:5, fill: 'var(--primary)'}} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            {censoredMonths.length > 0 && (
              <p style={{fontSize: '12px', color: 'var(--text-muted)', marginTop: '8px', marginBottom: 0}}>
                ⓘ 음영 구간({firstCensoredMonth}~{lastMonth})은 아직 12개월 관측이 끝나지 않아 &quot;시장 실질 부도율&quot;을 집계할 수 없습니다.
              </p>
            )}
          </div>
        </div>

        <div className="flex-col" style={{gap: '12px'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <TrendingUp size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>업종별 리스크 매트릭스</h2>
          </div>
          <div className="card">
            <div style={{width: '100%', height: '300px'}}>
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 35, right: 35, left: -10, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis type="number" dataKey="x" name="기존 평가 위험도" unit="%" domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.25 * 10) / 10]} tick={{fill: 'var(--text-muted)', fontSize: 12, fontWeight: 600}} axisLine={{stroke: '#e5e7eb'}} tickLine={false} />
                  <YAxis type="number" dataKey="y" name="ERM 고위험률" unit="%" domain={[0, (dataMax: number) => Math.max(35, Math.ceil(dataMax * 1.25))]} tick={{fill: 'var(--text-muted)', fontSize: 12, fontWeight: 600}} axisLine={{stroke: '#e5e7eb'}} tickLine={false} />
                  <ZAxis type="number" dataKey="z" range={[280, 950]} name="기업 수" />
                  <RechartsTooltip 
                    cursor={{strokeDasharray: '3 3'}} 
                    content={({ active, payload }) => {
                      if (active && payload && payload.length) {
                        const d = payload[0].payload;
                        return (
                          <div style={{backgroundColor: 'rgba(255, 255, 255, 0.98)', border: '1px solid var(--border)', borderRadius: '8px', padding: '12px', boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)'}}>
                            <p className="font-bold" style={{margin: '0 0 8px 0', fontSize: '15px', color: d.color || 'var(--text-main)', borderBottom: '1px solid var(--border)', paddingBottom: '6px'}}>
                              {d.fullName || d.name}
                            </p>
                            <p className="font-medium" style={{margin: '0 0 4px 0', fontSize: '13px', color: 'var(--text-muted)'}}>
                              기존 평가 위험도: <span style={{color: 'var(--text-main)', fontWeight: 700}}>{d.x}%</span>
                            </p>
                            <p className="font-medium" style={{margin: '0 0 4px 0', fontSize: '13px', color: 'var(--text-muted)'}}>
                              ERM 고위험률: <span style={{color: d.color || 'var(--danger)', fontWeight: 700}}>{d.y}%</span>
                            </p>
                            <p className="font-medium" style={{margin: 0, fontSize: '13px', color: 'var(--text-muted)'}}>
                              해당 업종 기업 수: <span style={{color: 'var(--text-main)', fontWeight: 700}}>{d.z}개사</span>
                            </p>
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  <Scatter name="업종" data={scatterData}>
                    {scatterData.map((entry: any, idx: number) => (
                      <Cell key={`cell-${idx}`} fill={entry.color} fillOpacity={0.75} stroke={entry.color} strokeWidth={2} />
                    ))}
                    <LabelList dataKey="name" content={CustomScatterLabel} />
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </div>
          </div>
        </div>

        {/* 신규 추가: 등급 분포 바 차트 */}
        <div className="flex-col" style={{gap: '12px', gridColumn: '1 / -1', marginTop: '12px'}}>
          <div className="flex-row" style={{gap: '8px'}}>
            <BarChartIcon size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>전체 포트폴리오 ⚡ ERM 리스크 평가등급 분포 (G1 ~ G5)</h2>
          </div>
          <div className="card">
            <div style={{width: '100%', height: '300px'}}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.grade_distribution} margin={{ top: 20, right: 30, left: -20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                  <XAxis dataKey="Z_GRADE" tick={{fill: 'var(--text-muted)', fontSize: 12, fontWeight: 600}} dy={10} axisLine={{stroke: '#e5e7eb'}} tickLine={false} />
                  <YAxis tick={{fill: 'var(--text-muted)', fontSize: 12}} axisLine={{stroke: '#e5e7eb'}} tickLine={false} />
                  <RechartsTooltip 
                    cursor={{fill: 'rgba(0,0,0,0.02)'}}
                    contentStyle={{backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)', borderRadius: '8px'}} 
                  />
                  <Bar dataKey="cnt" name="기업 수" radius={[4, 4, 0, 0]} maxBarSize={60}>
                    {data.grade_distribution.map((entry: any, index: number) => {
                      const color = ['G4', 'G5'].includes(entry.Z_GRADE) ? 'var(--danger)' : 
                                    entry.Z_GRADE === 'G3' ? 'var(--warning)' : 'var(--safe)';
                      return <Cell key={`cell-${index}`} fill={color} />;
                    })}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* 신규 추가: 예측 성공/실패 벤다이어그램 (실제 부도 기업 기준 ERM vs 내부등급) */}
        {predictionComparison && (
          <div className="flex-col" style={{gap: '12px', gridColumn: '1 / -1', marginTop: '12px'}}>
            <div className="flex-row" style={{gap: '8px'}}>
              <TrendingUp size={20} color="var(--primary)" />
              <h2 className="font-semibold" style={{margin: 0}}>부도 예측 성공/실패 비교 (ERM vs 은행 내부등급)</h2>
            </div>
            <div className="card">
              <PredictionVenn pc={predictionComparison} />
            </div>
          </div>
        )}

      </div>
  );
}
