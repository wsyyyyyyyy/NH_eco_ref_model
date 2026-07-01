export function getIndustryName(codeStr: string | number): string {
    if (!codeStr) return '분류불명';
    
    // Convert to string and handle floats like "68112.0"
    let codeString = String(codeStr).split('.')[0];
    
    // Ensure it's treated as a number for range checks
    const code = parseInt(codeString, 10);
    
    if (isNaN(code)) return String(codeStr);
    
    // Extract the first 2 digits (division code in KSIC)
    let division: number;
    if (codeString.length <= 2) {
        // Already a division code (e.g., from backend grouping)
        division = parseInt(codeString, 10);
    } else {
        // 5-digit or 4-digit raw KSIC code
        const paddedCode = codeString.padStart(5, '0');
        division = parseInt(paddedCode.substring(0, 2), 10);
    }

    if (division >= 1 && division <= 3) return '농업, 임업 및 어업';
    if (division >= 5 && division <= 8) return '광업';
    if (division >= 10 && division <= 34) return '제조업';
    if (division === 35) return '전기, 가스 공급업';
    if (division >= 36 && division <= 39) return '수도, 하수, 폐기물 처리업';
    if (division >= 41 && division <= 42) return '건설업';
    if (division >= 45 && division <= 47) return '도매 및 소매업';
    if (division >= 49 && division <= 52) return '운수 및 창고업';
    if (division >= 55 && division <= 56) return '숙박 및 음식점업';
    if (division >= 58 && division <= 63) return '정보통신업';
    if (division >= 64 && division <= 66) return '금융 및 보험업';
    if (division === 68) return '부동산업';
    if (division >= 70 && division <= 73) return '전문, 과학 기술 서비스업';
    if (division >= 74 && division <= 76) return '사업시설 관리 지원업';
    if (division === 84) return '공공 행정 및 국방';
    if (division === 85) return '교육 서비스업';
    if (division >= 86 && division <= 87) return '보건업 및 사회복지 서비스업';
    if (division >= 90 && division <= 91) return '예술, 스포츠 서비스업';
    if (division >= 94 && division <= 96) return '협회 및 개인 서비스업';
    if (division >= 97 && division <= 98) return '가구 내 고용활동';
    if (division === 99) return '국제 기관';
    
    return '기타 업종';
}
