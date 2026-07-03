import { useEffect, useState } from 'react';
import { BarChart, Bar, ScatterChart, Scatter, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, CartesianGrid, ZAxis, LabelList, Cell } from 'recharts';
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

// 벤다이어그램 안 라벨 대신, 영역 안쪽 점(dot)에서 바깥 뱃지로 이어지는 리더라인 + 색상 강조 뱃지.
const VennBadge = ({ dot, to, align = 'start', label, value, color, bg }: any) => {
  const textX = align === 'end' ? to.x - 6 : to.x + 6;
  const badgeW = align === 'end' ? -68 : 68;
  return (
    <g>
      <circle cx={dot.x} cy={dot.y} r="3.5" fill={color} />
      <line x1={dot.x} y1={dot.y} x2={to.x} y2={to.y} stroke={color} strokeWidth="1.5" />
      <rect x={align === 'end' ? to.x + badgeW : to.x} y={to.y - 15} width={Math.abs(badgeW)} height="30" rx="8" fill={bg} stroke={color} strokeWidth="1" />
      <text x={textX + (align === 'end' ? badgeW + 6 : 0)} y={to.y - 3} textAnchor={align} fontSize="10.5" fontWeight={700} fill={color}>{label}</text>
      <text x={textX + (align === 'end' ? badgeW + 6 : 0)} y={to.y + 13} textAnchor={align} fontSize="16" fontWeight={800} fill={color}>{value}</text>
    </g>
  );
};

const PredictionVenn = ({ pc }: { pc: any }) => {
  if (!pc) return null;
  const { both, erm_only, internal_only, neither, total, lead_time, grade_lag } = pc;
  const caughtTotal = both + erm_only + internal_only;
  const catchRate = total > 0 ? ((caughtTotal / total) * 100).toFixed(1) : '0';
  const blindSpotRate = total > 0 ? ((erm_only / total) * 100).toFixed(1) : '0';

  // r2(내부) 원은 기본적으로 r1(ERM) 원 안에 완전히 내포되도록 배치하고(내부만 포착=0인 실제
  // 데이터를 정직하게 반영), internal_only가 존재하면 그 비율만큼 오른쪽으로 살짝 튀어나오게 함.
  const r1 = 70, r2 = 48, cx1 = 128, cy = 128;
  const protrusion = (internal_only / Math.max(1, internal_only + both)) * r2 * 1.3;
  const cx2 = cx1 + Math.min(r1 - 6, (r1 - r2) + protrusion);
  const ERM_COLOR = '#3b82f6', BOTH_COLOR = '#b45309', NEITHER_COLOR = '#64748b';

  return (
    <div className="flex-col" style={{gap: '16px'}}>
      <div className="flex-row" style={{gap: '16px', alignItems: 'center', flexWrap: 'wrap'}}>
        <svg width="320" height="266" viewBox="0 0 320 266" style={{flexShrink: 0}}>
          <circle cx={cx1} cy={cy} r={r1} fill={ERM_COLOR} fillOpacity="0.22" stroke={ERM_COLOR} strokeWidth="2" />
          <circle cx={cx2} cy={cy} r={r2} fill="#fbbf24" fillOpacity="0.4" stroke="#f59e0b" strokeWidth="2" />

          <VennBadge dot={{x: cx1 - r1 * 0.5, y: cy - r1 * 0.42}} to={{x: 26, y: 44}} align="start"
            label="ERM만 포착" value={erm_only} color={ERM_COLOR} bg="#eff6ff" />
          <VennBadge dot={{x: cx2 - 4, y: cy + r2 * 0.35}} to={{x: 226, y: 150}} align="start"
            label="둘 다 포착" value={both} color={BOTH_COLOR} bg="#fffbeb" />
          <VennBadge dot={{x: cx2 + r2 * 0.55, y: cy - r2 * 0.75}} to={{x: 210, y: 40}} align="start"
            label="내부만 포착" value={internal_only} color="#b45309" bg="#fff7ed" />

          <circle cx="30" cy={cy + r1 + 30} r="3.5" fill={NEITHER_COLOR} />
          <text x="42" y={cy + r1 + 30} textAnchor="start" fontSize="12" fontWeight={600} fill={NEITHER_COLOR}>둘 다 놓침 {neither}개</text>
          <text x="42" y={cy + r1 + 48} textAnchor="start" fontSize="12" fontWeight={600} fill={NEITHER_COLOR}>실제 부도 기업 총 {total}개 (내부등급 이력 보유분)</text>
        </svg>
        <div className="flex-col" style={{gap: '14px', flex: 1, minWidth: '160px'}}>
          <div>
            <div className="font-semibold" style={{color: 'var(--text-muted)', fontSize: '13px'}}>평균 조기경보 리드타임</div>
            <div className="font-extrabold" style={{fontSize: '26px', color: 'var(--primary)'}}>
              {lead_time?.avg_months != null ? `+${lead_time.avg_months}개월` : '-'}
            </div>
          </div>
          <div className="flex-row" style={{gap: '16px', flexWrap: 'wrap', rowGap: '10px'}}>
            <div>
              <div style={{fontSize: '12px', color: 'var(--text-muted)', whiteSpace: 'nowrap'}}>전체 포착률</div>
              <div className="font-bold" style={{fontSize: '18px'}}>{catchRate}%</div>
            </div>
            <div>
              <div style={{fontSize: '12px', color: 'var(--text-muted)', whiteSpace: 'nowrap'}}>ERM 단독 사각지대</div>
              <div className="font-bold" style={{fontSize: '18px', color: 'var(--danger)'}}>{blindSpotRate}%</div>
            </div>
            <div>
              <div style={{fontSize: '12px', color: 'var(--text-muted)', whiteSpace: 'nowrap'}}>등급하향의 사후 반영 비율</div>
              <div className="font-bold" style={{fontSize: '18px', color: 'var(--warning)'}}>{grade_lag?.after_default_pct != null ? `${grade_lag.after_default_pct}%` : '-'}</div>
            </div>
          </div>
        </div>
      </div>
      <p style={{fontSize: '12px', color: 'var(--text-muted)', margin: 0}}>
        실제 부도 기업 총 {total}개(내부등급 이력 보유분) 중, 내부등급이 A→B로 전환되는 시점이 관측된 {lead_time?.n}개사 기준 ERM이 내부등급 하향보다 평균 {lead_time?.avg_months}개월 먼저 고위험(G4/G5)으로 경고했습니다.
        (내부등급이 데이터 시작 시점부터 이미 &apos;B&apos;였던 {lead_time?.left_censored_excluded}개사는 하향 시점을 알 수 없어 이 평균에서 제외 — 여전히 &quot;둘 다 포착&quot;에는 포함됩니다.)
        {grade_lag?.total ? ` 한편 실제 부도일자와 대조한 결과, 내부등급 A→B 전환이 관측된 ${grade_lag.total}개사 중 ${grade_lag.after_default_cnt}개사(${grade_lag.after_default_pct}%)는 부도가 이미 발생한 뒤(중앙값 ${Math.abs(grade_lag.median_lead_months ?? 0)}개월 후)에야 등급이 하향되어, 내부등급 하향의 상당수는 조기경보가 아닌 사후 반영에 가까웠습니다. (이 ${grade_lag.after_default_cnt}개사는 부도 시점 이전엔 B등급이 존재하지 않아 "둘 다 포착"이 아닌 "ERM만 포착"으로 이미 집계됩니다.)` : ''}
      </p>
    </div>
  );
};

export default function GlobalDashboard({ baseYm = '202402' }: { baseYm?: string }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [useRealData, setUseRealData] = useState(true);
  const [predictionComparison, setPredictionComparison] = useState<any>(null);

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
            <span className="font-semibold" style={{color: 'var(--text-muted)'}}>관측 대상 전체 기업 수</span>
          </div>
          <div className="flex-row" style={{alignItems: 'baseline', gap: '8px'}}>
            <div className="font-extrabold" style={{fontSize: '36px'}}>{data.total_companies.toLocaleString()}</div>
            <span className="font-medium" style={{color: 'var(--text-muted)'}}>개사</span>
          </div>
          <p className="font-regular" style={{marginTop: '12px', fontSize: '12px'}}>전체 관측기간(2021.01~2026.06) 내내 데이터가 있는 고정 패널 — 기준월을 바꿔도 동일</p>
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

      <div className="flex-col" style={{gap: '12px'}}>
        <div className="flex-row" style={{gap: '8px'}}>
          <TrendingUp size={20} color="var(--primary)" />
          <h2 className="font-semibold" style={{margin: 0}}>업종별 리스크 매트릭스</h2>
        </div>
        <div className="card">
          <div style={{width: '100%', height: '340px'}}>
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

      {/* 신규 추가: 예측 성공/실패 벤다이어그램 + 등급 분포 (같은 행에 나란히 배치) */}
        <div className="grid-2" style={{marginTop: '12px'}}>
          <div className="flex-col" style={{gap: '12px'}}>
            <div className="flex-row" style={{gap: '8px'}}>
              <TrendingUp size={20} color="var(--primary)" />
              <h2 className="font-semibold" style={{margin: 0}}>부도 예측 성공/실패 비교 (ERM vs 은행 내부등급)</h2>
            </div>
            <div className="card">
              {predictionComparison
                ? <PredictionVenn pc={predictionComparison} />
                : <div style={{padding: '60px 0', textAlign: 'center', color: 'var(--text-muted)'}}>불러오는 중...</div>}
            </div>
          </div>

          <div className="flex-col" style={{gap: '12px'}}>
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
        </div>

      </div>
  );
}
