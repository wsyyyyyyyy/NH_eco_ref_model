import { useEffect, useState } from 'react';
import { Search, ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { branchBorrowersMock } from '../utils/mockData';
import { getIndustryName } from '../utils/industry';
import { API_BASE_URL } from '../config';

export default function BranchDashboard({ branch = 'VB001', baseYm = '202402' }: { branch?: string, baseYm?: string }) {
  const [borrowers, setBorrowers] = useState<any[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [industryFilter, setIndustryFilter] = useState('');
  const [legacyGradeFilter, setLegacyGradeFilter] = useState('');
  const [ermGradeFilter, setErmGradeFilter] = useState('');
  const [activeTabFilter, setActiveTabFilter] = useState<'all' | 'highRisk' | 'mismatch'>('all');
  const [useRealData, setUseRealData] = useState(true);
  const [loading, setLoading] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 20;

  useEffect(() => {
    setCurrentPage(1);
  }, [searchTerm, industryFilter, legacyGradeFilter, ermGradeFilter, activeTabFilter, branch, baseYm, useRealData]);

  useEffect(() => {
    setBorrowers([]); // 로딩 시각적 효과
    if (useRealData) {
      setLoading(true);
      fetch(`${API_BASE_URL}/api/borrowers/?branch_code=${branch}&base_ym=${baseYm}&limit=1500`)
        .then(res => res.json())
        .then(data => {
          if (Array.isArray(data)) {
            setBorrowers(data);
          }
          setLoading(false);
        })
        .catch(err => {
          console.error("Failed to fetch real data:", err);
          setLoading(false);
        });
    } else {
      setTimeout(() => {
          let filtered = branchBorrowersMock.filter((d: any) => d.V_BRANCH_CODE ? d.V_BRANCH_CODE === branch : true);
          if (baseYm === '202401') {
              filtered = filtered.slice(0, Math.floor(filtered.length * 0.92));
          } else if (baseYm === '202312') {
              filtered = filtered.slice(0, Math.floor(filtered.length * 0.85));
          }
          setBorrowers(filtered);
      }, 200);
    }
  }, [branch, baseYm, useRealData]);

  const getLegacyGrade = (grade: string) => {
    const map: Record<string, string> = {
      'G1': '2등급 (AA+)',
      'G2': '5등급 (A0)',
      'G3': '8등급 (BBB0)',
      'G4': '12등급 (BB-)',
      'G5': '16등급 (C)'
    };
    return map[grade] || `${grade}등급`;
  };

  const getErmGrade = (prob: number) => {
    if (prob >= 0.6) return 'G5 (부실우려)';
    if (prob >= 0.3) return 'G4 (고위험)';
    if (prob >= 0.1) return 'G3 (주의요망)';
    if (prob >= 0.02) return 'G2 (안정권)';
    return 'G1 (최우량)';
  };

  const checkIsBlindSpot = (b: any) => b.PROB_FULL >= 0.25 && b.OLD_PROB <= 0.06; // 기존평가 확률은 6% 이하로 낮았으나 ERM 실측은 25% 이상 고위험으로 판명된 AI 조기경보(사각지대) 대상

  const filteredData = borrowers.filter(b => {
    const legacyStr = getLegacyGrade(b.Z_GRADE);
    const ermStr = getErmGrade(b.PROB_FULL);
    const matchSearch = String(b.V_BZNO).includes(searchTerm) || 
                        legacyStr.toLowerCase().includes(searchTerm.toLowerCase()) || 
                        ermStr.toLowerCase().includes(searchTerm.toLowerCase()) ||
                        String(b.Z_GRADE).toLowerCase().includes(searchTerm.toLowerCase());
    const matchInd = industryFilter ? getIndustryName(b.STD_INDS_CFC) === industryFilter : true;
    const matchLegacy = legacyGradeFilter ? b.Z_GRADE === legacyGradeFilter : true;
    const matchErm = ermGradeFilter ? ermStr.startsWith(ermGradeFilter) : true;
    const matchTab = activeTabFilter === 'highRisk' ? (b.PROB_FULL >= 0.25) : 
                     activeTabFilter === 'mismatch' ? checkIsBlindSpot(b) : true;
    return matchSearch && matchInd && matchLegacy && matchErm && matchTab;
  });

  const totalPages = Math.ceil(filteredData.length / itemsPerPage) || 1;
  const paginatedData = filteredData.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage);

  const highRiskCount = borrowers.filter(b => b.PROB_FULL >= 0.25).length;
  const mismatchCount = borrowers.filter(b => checkIsBlindSpot(b)).length;

  return (
    <div className="flex-col" style={{gap: '24px'}}>
      <div className="flex-row" style={{justifyContent: 'space-between', marginBottom: '8px', alignItems: 'center'}}>
        <div className="flex-row" style={{gap: '16px', alignItems: 'center'}}>
          <div className="flex-col" style={{gap: '8px'}}>
            <h1 className="font-bold">{branch} 지점 대시보드</h1>
            <p className="font-regular">관할 지점의 차주 리스트 및 고위험 모니터링 현황</p>
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
        
        <div className="flex-row" style={{gap: '10px', flexWrap: 'wrap'}}>
          <select 
            className="card" 
            style={{padding: '8px 14px', fontSize: '13px', fontWeight: 600, minWidth: '130px'}}
            value={industryFilter} 
            onChange={(e) => setIndustryFilter(e.target.value)}
          >
            <option value="">모든 업종</option>
            {Array.from(new Set(borrowers.map(b => getIndustryName(b.STD_INDS_CFC)))).sort().map(indName => (
              <option key={indName as string} value={indName as string}>{indName as string}</option>
            ))}
          </select>

          <select 
            className="card" 
            style={{padding: '8px 14px', fontSize: '13px', fontWeight: 600, minWidth: '135px'}}
            value={legacyGradeFilter} 
            onChange={(e) => setLegacyGradeFilter(e.target.value)}
          >
            <option value="">🏛️ 기존 평가 등급</option>
            <option value="G1">2등급 (AA+)</option>
            <option value="G2">5등급 (A0)</option>
            <option value="G3">8등급 (BBB0)</option>
            <option value="G4">12등급 (BB-)</option>
            <option value="G5">16등급 (C)</option>
          </select>

          <select 
            className="card" 
            style={{padding: '8px 14px', fontSize: '13px', fontWeight: 600, minWidth: '135px'}}
            value={ermGradeFilter} 
            onChange={(e) => setErmGradeFilter(e.target.value)}
          >
            <option value="">⚡ ERM 등급</option>
            <option value="G1">G1 (최우량)</option>
            <option value="G2">G2 (안정권)</option>
            <option value="G3">G3 (주의요망)</option>
            <option value="G4">G4 (고위험)</option>
            <option value="G5">G5 (부실우려)</option>
          </select>

          <div className="card flex-row" style={{padding: '8px 14px', gap: '8px', minWidth: '220px'}}>
            <Search size={16} color="var(--text-muted)" />
            <input 
              type="text" 
              placeholder="기업명_사업자번호_등급 검색..." 
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{border: 'none', outline: 'none', width: '100%', fontSize: '13px'}}
            />
          </div>
        </div>
      </div>

      {/* Interactive Portfolio Summary Cards */}
      <div className="flex-row" style={{gap: '16px', width: '100%', flexWrap: 'wrap'}}>
        <div 
          onClick={() => setActiveTabFilter('all')}
          className="card flex-row" 
          style={{
            flex: 1, 
            minWidth: '280px',
            justifyContent: 'space-between', 
            backgroundColor: activeTabFilter === 'all' ? '#eff6ff' : 'white', 
            border: activeTabFilter === 'all' ? '2px solid #3b82f6' : '1px solid var(--border)', 
            boxShadow: activeTabFilter === 'all' ? '0 4px 12px rgba(59, 130, 246, 0.15)' : '0 2px 6px rgba(0,0,0,0.04)', 
            padding: '20px 24px', 
            cursor: 'pointer',
            transition: 'all 0.2s ease',
            alignItems: 'center'
          }}
        >
          <div className="flex-col" style={{gap: '8px'}}>
            <div className="flex-row" style={{gap: '6px', alignItems: 'center'}}>
              <span style={{fontSize: '18px'}}>🏢</span>
              <p className="font-semibold" style={{fontSize: '14px', color: activeTabFilter === 'all' ? '#1d4ed8' : 'var(--text-muted)', margin: 0}}>지점 총 차주 수</p>
            </div>
            <div className="flex-row" style={{alignItems: 'baseline', gap: '8px'}}>
              <div className="font-extrabold" style={{fontSize: '32px', color: activeTabFilter === 'all' ? '#1e40af' : 'var(--text-main)'}}>{borrowers.length.toLocaleString()}</div>
              <span className="font-medium" style={{fontSize: '14px', color: 'var(--text-muted)'}}>개사 전체보기</span>
            </div>
          </div>
          {activeTabFilter === 'all' && <span style={{fontSize: '12px', fontWeight: 700, color: '#3b82f6', backgroundColor: '#dbeafe', padding: '4px 10px', borderRadius: '12px'}}>✓ 선택됨</span>}
        </div>

        <div 
          onClick={() => setActiveTabFilter('highRisk')}
          className="card flex-row" 
          style={{
            flex: 1, 
            minWidth: '280px',
            justifyContent: 'space-between', 
            backgroundColor: activeTabFilter === 'highRisk' ? '#fef2f2' : 'white', 
            border: activeTabFilter === 'highRisk' ? '2px solid var(--danger)' : '1px solid var(--border)', 
            boxShadow: activeTabFilter === 'highRisk' ? '0 4px 12px rgba(239, 68, 68, 0.15)' : '0 2px 6px rgba(0,0,0,0.04)', 
            padding: '20px 24px', 
            cursor: 'pointer',
            transition: 'all 0.2s ease',
            alignItems: 'center'
          }}
        >
          <div className="flex-col" style={{gap: '8px'}}>
            <div className="flex-row" style={{gap: '6px', alignItems: 'center'}}>
              <span style={{fontSize: '18px'}}>⚡</span>
              <p className="font-semibold" style={{fontSize: '14px', color: activeTabFilter === 'highRisk' ? '#b91c1c' : 'var(--text-muted)', margin: 0}}>ERM 분석 고위험군</p>
            </div>
            <div className="flex-row" style={{alignItems: 'baseline', gap: '8px'}}>
              <div className="font-extrabold" style={{fontSize: '32px', color: 'var(--danger)'}}>{highRiskCount.toLocaleString()}</div>
              <span className="font-medium" style={{fontSize: '14px', color: 'var(--text-muted)'}}>개사 (G4·G5)</span>
            </div>
          </div>
          {activeTabFilter === 'highRisk' && <span style={{fontSize: '12px', fontWeight: 700, color: 'var(--danger)', backgroundColor: '#fee2e2', padding: '4px 10px', borderRadius: '12px'}}>✓ 선택됨</span>}
        </div>

        <div 
          onClick={() => setActiveTabFilter('mismatch')}
          className="card flex-row" 
          style={{
            flex: 1, 
            minWidth: '280px',
            justifyContent: 'space-between', 
            backgroundColor: activeTabFilter === 'mismatch' ? '#fffbeb' : 'white', 
            border: activeTabFilter === 'mismatch' ? '2px solid var(--warning)' : '1px solid var(--border)', 
            boxShadow: activeTabFilter === 'mismatch' ? '0 4px 12px rgba(245, 158, 11, 0.15)' : '0 2px 6px rgba(0,0,0,0.04)', 
            padding: '20px 24px', 
            cursor: 'pointer',
            transition: 'all 0.2s ease',
            alignItems: 'center'
          }}
        >
          <div className="flex-col" style={{gap: '8px'}}>
            <div className="flex-row" style={{gap: '6px', alignItems: 'center'}}>
              <span style={{fontSize: '18px'}}>🚨</span>
              <p className="font-semibold" style={{fontSize: '14px', color: activeTabFilter === 'mismatch' ? '#b45309' : 'var(--text-muted)', margin: 0}}>잠재 리스크 (등급 괴리)</p>
            </div>
            <div className="flex-row" style={{alignItems: 'baseline', gap: '8px'}}>
              <div className="font-extrabold" style={{fontSize: '32px', color: 'var(--warning)'}}>{mismatchCount.toLocaleString()}</div>
              <span className="font-medium" style={{fontSize: '14px', color: 'var(--text-muted)'}}>건 (AI 조기경보)</span>
            </div>
          </div>
          {activeTabFilter === 'mismatch' && <span style={{fontSize: '12px', fontWeight: 700, color: '#d97706', backgroundColor: '#fef3c7', padding: '4px 10px', borderRadius: '12px'}}>✓ 선택됨</span>}
        </div>
      </div>

      <div className="card" style={{padding: '0', overflowX: 'auto'}}>
        <table style={{width: '100%', minWidth: '1050px'}}>
          <thead>
            <tr>
              <th style={{minWidth: '190px'}}>기업명 (사업자번호)</th>
              <th style={{minWidth: '130px'}}>업종</th>
              <th style={{minWidth: '140px', textAlign: 'center'}}>🏛️ 기존평가 등급</th>
              <th style={{minWidth: '120px', textAlign: 'right'}}>기존모델 확률</th>
              <th style={{minWidth: '130px', textAlign: 'center'}}>⚡ ERM 등급</th>
              <th style={{minWidth: '120px', textAlign: 'right'}}>⚡ ERM 확률</th>
              <th style={{minWidth: '120px', textAlign: 'center'}}>NICE (전월→당월)</th>
              <th style={{minWidth: '120px', textAlign: 'center'}}>KIS (전월→당월)</th>
              <th style={{minWidth: '90px', textAlign: 'center'}}>상세분석</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={9} style={{textAlign: 'center', padding: '60px 0', color: 'var(--text-muted)'}}>
                  <div className="flex-col" style={{alignItems: 'center', gap: '12px'}}>
                    <div style={{fontSize: '24px'}}>⏳</div>
                    <span className="font-bold">DuckDB에서 실제 차주 패널 데이터를 분석 중입니다...</span>
                  </div>
                </td>
              </tr>
            ) : paginatedData.map((item, idx) => {
              const isBlindSpot = checkIsBlindSpot(item); // 기존 모델과 큰 괴리 (AI 조기경보 대상)
              
              return (
                <tr key={idx} style={{backgroundColor: isBlindSpot ? 'rgba(239, 68, 68, 0.02)' : 'transparent'}}>
                  <td>
                    <div className="flex-col" style={{gap: '4px'}}>
                      <div className="flex-row" style={{gap: '6px', alignItems: 'center'}}>
                        <span className="font-bold" style={{fontSize: '15px'}}>기업_{item.V_BZNO}</span>
                        {isBlindSpot && (
                          <span style={{backgroundColor: '#fef2f2', color: 'var(--danger)', border: '1px solid #fca5a5', padding: '2px 6px', borderRadius: '4px', fontSize: '11px', fontWeight: 800, whiteSpace: 'nowrap'}}>
                            🚨 AI 조기경보
                          </span>
                        )}
                      </div>
                      <span className="font-regular" style={{fontSize: '12px', color: 'var(--text-muted)'}}>{item.V_BZNO}</span>
                    </div>
                  </td>
                  <td style={{fontSize: '14px'}}>{getIndustryName(item.STD_INDS_CFC)}</td>
                  <td style={{textAlign: 'center'}}>
                    <span className="badge" style={{backgroundColor: '#f1f5f9', color: '#475569', fontSize: '12px', fontWeight: 700, border: '1px solid #cbd5e1'}}>
                      {getLegacyGrade(item.Z_GRADE)}
                    </span>
                  </td>
                  <td style={{textAlign: 'right'}}>
                    <div className="flex-col" style={{alignItems: 'flex-end', gap: '4px'}}>
                      <span className="font-bold" style={{color: '#64748b'}}>
                        {(item.OLD_PROB * 100).toFixed(2)}%
                      </span>
                      <div style={{width: '60px', height: '4px', backgroundColor: 'var(--bg-main)', borderRadius: '2px', overflow: 'hidden'}}>
                        <div style={{width: `${item.OLD_PROB * 100}%`, height: '100%', backgroundColor: '#94a3b8'}} />
                      </div>
                    </div>
                  </td>
                  <td style={{textAlign: 'center'}}>
                    <span className="badge badge-primary" style={{padding: '4px 10px', fontSize: '12px', fontWeight: 800, backgroundColor: ['G4 (고위험)','G5 (부실우려)'].includes(getErmGrade(item.PROB_FULL)) ? '#fee2e2' : ['G3 (주의요망)'].includes(getErmGrade(item.PROB_FULL)) ? '#fef3c7' : '#d1fae5', color: ['G4 (고위험)','G5 (부실우려)'].includes(getErmGrade(item.PROB_FULL)) ? '#dc2626' : ['G3 (주의요망)'].includes(getErmGrade(item.PROB_FULL)) ? '#d97706' : '#059669', border: 'none'}}>
                      {getErmGrade(item.PROB_FULL)}
                    </span>
                  </td>
                  <td style={{textAlign: 'right'}}>
                    <div className="flex-col" style={{alignItems: 'flex-end', gap: '4px'}}>
                      <span className="font-extrabold" style={{color: item.PROB_FULL >= 0.3 ? 'var(--danger)' : item.PROB_FULL >= 0.1 ? 'var(--warning)' : 'var(--safe)', fontSize: '15px'}}>
                        {(item.PROB_FULL * 100).toFixed(2)}%
                      </span>
                      <div style={{width: '60px', height: '4px', backgroundColor: 'var(--bg-main)', borderRadius: '2px', overflow: 'hidden'}}>
                        <div style={{width: `${item.PROB_FULL * 100}%`, height: '100%', backgroundColor: item.PROB_FULL >= 0.3 ? 'var(--danger)' : item.PROB_FULL >= 0.1 ? 'var(--warning)' : 'var(--safe)'}} />
                      </div>
                    </div>
                  </td>
                  <td style={{textAlign: 'center', fontSize: '13px'}}>
                    <span style={{color: 'var(--text-muted)'}}>{item.NICE_GRADE_PREV}</span>
                    <span style={{margin: '0 6px', color: 'var(--border)'}}>→</span>
                    <span className="font-bold" style={{color: item.NICE_GRADE_CUR < item.NICE_GRADE_PREV ? 'var(--danger)' : 'var(--text-main)'}}>{item.NICE_GRADE_CUR}</span>
                  </td>
                  <td style={{textAlign: 'center', fontSize: '13px'}}>
                    <span style={{color: 'var(--text-muted)'}}>{item.KIS_GRADE_PREV}</span>
                    <span style={{margin: '0 6px', color: 'var(--border)'}}>→</span>
                    <span className="font-bold" style={{color: item.KIS_GRADE_CUR < item.KIS_GRADE_PREV ? 'var(--danger)' : 'var(--text-main)'}}>{item.KIS_GRADE_CUR}</span>
                  </td>
                  <td style={{textAlign: 'center'}}>
                    <Link to={`/borrower/${item.V_BZNO}`} style={{textDecoration: 'none'}}>
                      <button className="btn btn-ghost" style={{minWidth: 'auto', padding: '8px 12px'}}>
                        <ChevronRight size={20} />
                      </button>
                    </Link>
                  </td>
                </tr>
              );
            })}
            {!loading && filteredData.length === 0 && (
              <tr>
                <td colSpan={9} style={{textAlign: 'center', padding: '40px', color: 'var(--text-muted)'}}>데이터 없음</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 페이징 컨트롤 */}
      {!loading && filteredData.length > 0 && (
        <div className="card flex-row" style={{justifyContent: 'space-between', alignItems: 'center', padding: '16px 24px'}}>
          <span className="font-medium" style={{fontSize: '14px', color: 'var(--text-muted)'}}>
            총 <strong style={{color: 'var(--text-main)'}}>{filteredData.length}</strong>개 기업 중 {((currentPage - 1) * itemsPerPage) + 1} ~ {Math.min(currentPage * itemsPerPage, filteredData.length)}개 표시 (페이지 {currentPage} / {totalPages})
          </span>
          <div className="flex-row" style={{gap: '6px', alignItems: 'center'}}>
            <button 
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              className="btn"
              style={{padding: '6px 14px', fontSize: '13px', backgroundColor: currentPage === 1 ? '#f1f5f9' : 'var(--bg-main)', color: currentPage === 1 ? '#cbd5e1' : 'var(--text-main)', border: '1px solid var(--border)', cursor: currentPage === 1 ? 'not-allowed' : 'pointer'}}
            >
              이전
            </button>
            
            {Array.from({ length: Math.min(7, totalPages) }, (_, i) => {
              let pageNum: number;
              if (totalPages <= 7) {
                pageNum = i + 1;
              } else if (currentPage <= 4) {
                pageNum = i + 1;
              } else if (currentPage >= totalPages - 3) {
                pageNum = totalPages - 6 + i;
              } else {
                pageNum = currentPage - 3 + i;
              }
              
              return (
                <button
                  key={pageNum}
                  onClick={() => setCurrentPage(pageNum)}
                  style={{
                    width: '34px',
                    height: '34px',
                    borderRadius: '8px',
                    border: pageNum === currentPage ? 'none' : '1px solid var(--border)',
                    backgroundColor: pageNum === currentPage ? 'var(--primary)' : 'var(--bg-main)',
                    color: pageNum === currentPage ? 'white' : 'var(--text-main)',
                    fontWeight: pageNum === currentPage ? 700 : 500,
                    cursor: 'pointer',
                    fontSize: '13px'
                  }}
                >
                  {pageNum}
                </button>
              );
            })}

            <button 
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
              className="btn"
              style={{padding: '6px 14px', fontSize: '13px', backgroundColor: currentPage === totalPages ? '#f1f5f9' : 'var(--bg-main)', color: currentPage === totalPages ? '#cbd5e1' : 'var(--text-main)', border: '1px solid var(--border)', cursor: currentPage === totalPages ? 'not-allowed' : 'pointer'}}
            >
              다음
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
