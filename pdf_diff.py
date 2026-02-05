
import streamlit as st
import pdfplumber
import difflib
import re
import io

# -----------------------------------------------------------------------------
# 1. 텍스트 전처리 (Normalization)
#    - 의미 없는 문자(하이픈 등) 제거
#    - 종결 어미 통일 ('습니다' -> '다' 등)
# -----------------------------------------------------------------------------
def normalize_text(text):
    if not text:
        return ""

    # 줄바꿈을 공백으로 변경 (문단 내 줄바꿈 이슈 해결)
    text = text.replace('\n', ' ')

    # 1. 하이픈(-), 마이너스 기호 제거 (앞뒤 공백 포함해서 유연하게)
    text = re.sub(r'\s*[-]\s*', ' ', text)

    # 2. 불필요한 특수문자 제거 (선택 사항, 일단 하이픈 위주로)
    # text = re.sub(r'[^\w\s가-힣.]', '', text) 

    # 3. 한국어 종결어미 '습니다/봅니다/합니다' 등을 '다'로 통일
    #    예: "조사되었습니다" -> "조사되었다", "합니다" -> "한다"
    #    주의: 너무 과하게 줄이면 의미가 달라질 수 있으므로 대표적인 패턴만 처리
    text = re.sub(r'(했|였|았|었|겠)?(습니|옵니|비니)?다\b', r'\1다', text)
    text = re.sub(r'입니다\b', '이다', text)
    
    # 4. 공백 정규화 (연속된 공백을 하나로)
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

# -----------------------------------------------------------------------------
# 2. PDF 텍스트 추출
# -----------------------------------------------------------------------------
def extract_text_from_pdf(file_obj):
    text = ""
    try:
        with pdfplumber.open(file_obj) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        st.error(f"PDF 읽기 오류: {e}")
        return ""
    return text

# -----------------------------------------------------------------------------
# 3. Diff 계산 및 HTML 생성 (변경된 부분만 표시)
# -----------------------------------------------------------------------------

def compare_texts(text1, text2):
    # 전처리된 텍스트로 비교 (normalize_text 함수 사용)
    # 1. 기본적인 텍스트 정규화 (의미없는 문자 제거 등)
    norm1 = normalize_text(text1)
    norm2 = normalize_text(text2)
    
    # 2. 토큰화: 문자 단위로 비교 (Character-based diff)
    #    PDF는 띄어쓰기가 불규칙하므로, 단어 단위(split)보다는 문자 단위가 '알 러지' vs '알러지' 같은 케이스 처리에 유리합니다.
    tokens1 = list(norm1)
    tokens2 = list(norm2)
    
    # SequenceMatcher 사용
    matcher = difflib.SequenceMatcher(None, tokens1, tokens2)
    
    diff_html_parts = []
    
    # 변경 사항 감지
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        
        # 변경된 텍스트 추출
        deleted_text = "".join(tokens1[i1:i2])
        inserted_text = "".join(tokens2[j1:j2])
        
        # -------------------------------------------------------------------------
        # [핵심] 띄어쓰기/공백만 바뀐 경우 무시 (User Request 해결)
        # 예: "알 러지" vs "알러지" -> 공백 삭제됨 -> 내용(문자)은 같으므로 무시
        # -------------------------------------------------------------------------
        if tag == 'replace':
            # 공백을 모두 제거했을 때 동일하다면, 실질적인 차이가 아닌 것으로 간주
            if deleted_text.replace(" ", "") == inserted_text.replace(" ", ""):
                continue
        elif tag == 'delete':
            # 삭제된 내용이 공백뿐이면 무시
            if not deleted_text.strip():
                continue
        elif tag == 'insert':
            # 추가된 내용이 공백뿐이면 무시
            if not inserted_text.strip():
                continue

        # HTML 생성
        fragment = '<div style="margin-bottom: 8px; line-height: 1.6; font-size: 16px;">'
        
        if tag == 'replace':
            fragment += f'<span style="background-color: #ffeef0; color: #b31d28; text-decoration: line-through; padding: 2px 4px; border-radius: 4px; margin-right: 4px;">{deleted_text}</span>'
            fragment += '<span style="color: #999; margin: 0 4px;">→</span>' # 시각적 분리 (화살표)
            fragment += f'<span style="background-color: #e6ffed; color: #22863a; font-weight: bold; padding: 2px 4px; border-radius: 4px;">{inserted_text}</span>'
            
        elif tag == 'delete':
            fragment += f'<span style="background-color: #ffeef0; color: #b31d28; text-decoration: line-through; padding: 2px 4px; border-radius: 4px;">{deleted_text}</span>'
            
        elif tag == 'insert':
            fragment += f'<span style="background-color: #e6ffed; color: #22863a; font-weight: bold; padding: 2px 4px; border-radius: 4px;">{inserted_text}</span>'
            
        fragment += '</div>'
        diff_html_parts.append(fragment)
        
    return "".join(diff_html_parts) if diff_html_parts else None


# -----------------------------------------------------------------------------
# 4. Streamlit UI
# -----------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="스마트 PDF 문서 비교기", layout="wide")
    
    st.title("📄 스마트 PDF 문서 비교기")
    st.markdown("""
    두 개의 PDF 파일을 업로드하면, 서식이나 의미 없는 조사('습니다' 등) 차이는 무시하고 **실질적으로 변경된 내용만** 보여줍니다.
    """)
    
    col1, col2 = st.columns(2)
    
    with col1:
        file1 = st.file_uploader("이전 버전 파일 (PDF)", type=["pdf"], key="file1")
        
    with col2:
        file2 = st.file_uploader("새로운 버전 파일 (PDF)", type=["pdf"], key="file2")
        
    if file1 and file2:
        with st.spinner("문서를 분석하고 비교하는 중입니다..."):
            # 1. 텍스트 추출
            text1 = extract_text_from_pdf(file1)
            text2 = extract_text_from_pdf(file2)
            
            # 2. 비교 수행
            diff_result = compare_texts(text1, text2)
            
            st.divider()
            st.subheader("📊 비교 결과")
            
            if diff_result:
                # 결과 출력
                st.markdown(diff_result, unsafe_allow_html=True)
            else:
                # 차이가 없거나 정규화 후 동일해진 경우
                st.info("두 문서 간에 (의미 있는) 변경 사항이 없습니다.")
                st.markdown("Tip: '되었습니다' -> '되었다', '-' 기호 등은 무시하도록 처리되었습니다.")

if __name__ == "__main__":
    main()
