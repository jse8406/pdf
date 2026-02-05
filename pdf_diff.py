
import streamlit as st
import pdfplumber
import difflib
import re

# -----------------------------------------------------------------------------
# 1. 텍스트 전처리 (Normalization)
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# 1. 텍스트 전처리 (Normalization)
# -----------------------------------------------------------------------------
def normalize_text(text):
    if not text:
        return ""

    # 0. 노이즈 제거 (반복되는 웹사이트 UI 텍스트, URL, 시간 등)
    text = re.sub(r'(PDF|XML|HTML)\s*다운로드', '', text, flags=re.IGNORECASE)
    text = re.sub(r'변경\s*이력', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\d{2,4}[. ]+\d{1,2}[. ]+\d{1,2}[.]?', '', text) 
    text = re.sub(r'(오전|오후)\s*\d{1,2}\s*[:]\s*\d{2}(?:\s*[:]\s*\d{2})?', '', text) 
    text = re.sub(r'\b\d+\s*/\s*\d+\b', '', text) 
    text = re.sub(r'cacheSeq=[a-zA-Z0-9]+', '', text)
    
    # 1. 스마트 줄바꿈 처리 (Smart Reflow)
    #    무조건 줄바꿈을 없애면 목록이나 문단이 뭉개지므로, "의미 있는 줄바꿈"은 살립니다.
    #    (1) 문장이 끝나는 느낌(. : ) 뒤의 줄바꿈 -> 유지 (\n)
    #    (2) 목록 기호(•, -, 숫자.) 앞의 줄바꿈 -> 유지 (\n)
    #    (3) 그 외 어정쩡한 줄바꿈 -> 공백(' ')으로 치환 (Soft Wrap 처리)
    
    # 정규식 패턴: 줄바꿈 뒤에 "목록 기호"가 오거나, "문장 부호" 뒤에 줄바꿈이 있는 경우를 제외하고 공백화
    # 목록 기호: •, -, *, 숫자. (1. 2. 등)
    # 문장 부호: ., :, ], )
    
    def smart_join(match):
        prev_char = match.string[match.start()-1] # 줄바꿈 앞글자
        next_chunk = match.string[match.end()] if match.end() < len(match.string) else "" # 줄바꿈 뒷글자

        # Hard Wrap 조건 1: 문장 종료 부호 뒤
        if prev_char in ['.', ':', ']', ')', '>', '!', '?']:
            return '\n'
        
        # Hard Wrap 조건 2: 목록 기호 앞 ( •, -, 숫자.)
        if next_chunk in ['•', '-', '*', '[']:
            return '\n'
        # 숫자 + 점 (예: 1. ) 패턴 확인은 여기서 어렵지만, 일단 단순 기호만 체크
        
        # 그 외에는 Soft Wrap으로 간주하고 Join
        return ' '

    # 줄바꿈(\n)을 찾아서 스마트하게 처리
    # (주의: \n이 여러개면 하나로 취급하기 위해 re.sub 사용)
    text = re.sub(r'(?<!\n)\n(?!\n)', smart_join, text)
    
    # 2. 탭 제거
    text = text.replace('\t', ' ')

    # 3. 특수문자 제거 (가독성을 해치지 않는 선에서)
    #    단, 줄바꿈 보존을 위해 \n은 살려야 함.
    #    •, - 같은 목록 기호도 구조 파악을 위해 살려두는 것이 좋음.
    text = re.sub(r'[,\'"`]', ' ', text) # 콤마, 따옴표 등 아주 사소한 것만 제거
    
    # 괄호 등은 구조상 중요할 수 있으므로 유지하되, 지나친 기호만 정리
    # (사용자 요청에 따라 조절 가능)

    # 4. 한국어 어미/조사 완화
    text = re.sub(r'(했|였|았|었|겠)?(습니|옵니|비니)?다\b', r'\1다', text)
    text = re.sub(r'입니다\b', '이다', text)
    
    # 5. 공백 정규화 (연속된 공백 하나로, 단 \n은 건드리지 않음)
    text = re.sub(r'[ \t]+', ' ', text).strip()
    # \n 주위의 공백 정리
    text = re.sub(r' *\n *', '\n', text)
    
    return text

# -----------------------------------------------------------------------------
# 2. PDF 텍스트 추출 (스마트 섹션 필터링)
# -----------------------------------------------------------------------------
def extract_target_sections(full_text):
    """
    전체 텍스트에서 '효능·효과', '용법·용량', '사용상의 주의사항' 섹션만 추출합니다.
    괄호가 없는 헤더(예: '용법용량')도 유연하게 인식하며, 
    '성상', '저장방법' 등 불필요한 섹션이 나오면 추출을 멈춥니다.
    """
    
    # 1. 섹션 헤더로 의심되는 모든 라인을 찾습니다.
    keyword_pattern = r"(?:효\s*능|효\s*과|용\s*법|용\s*량|투\s*여|주\s*의\s*사\s*항|경\s*고|성\s*상|저\s*장|보\s*관|기\s*간|원\s*료|제\s*조|포\s*장|구\s*성)"
    header_regex = r"(?m)^[\s\d\.\•\[【\|·\-]*(?:" + keyword_pattern + r")[^\n]{0,50}$"
    
    matches = []
    for match in re.finditer(header_regex, full_text):
        matches.append({
            "start": match.start(),
            "end": match.end(),
            "text": match.group(0).strip()
        })
    
    if not matches:
        return ""
        
    extracted_parts = []
    
    target_groups = {
        "효능": ["효능", "효과"],
        "용법": ["용법", "용량", "투여"],
        "주의": ["주의", "경고", "환자"]
    }
    
    for i, header in enumerate(matches):
        clean_title = re.sub(r'[\s\[\]【】\.\d\•]', '', header['text'])
        
        is_target = False
        for key, text_list in target_groups.items():
            for t in text_list:
                if t in clean_title:
                    is_target = True
                    break
            if is_target: break
            
        if is_target:
            start_pos = header['end']
            if i < len(matches) - 1:
                end_pos = matches[i+1]['start']
            else:
                end_pos = len(full_text)
                
            content = full_text[start_pos:end_pos].strip()
            
            if len(content) < 2:
                continue
                
            extracted_parts.append(f"\n\n--- [{header['text']}] ---\n{content}")
            
    result = "".join(extracted_parts)
    return result if result else ""

def extract_text_from_pdf(file_obj):
    text = ""
    try:
        file_obj.seek(0)
        with pdfplumber.open(file_obj) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(x_tolerance=2, y_tolerance=3)
                if page_text:
                    text += page_text + "\n"
        
        relevant_text = extract_target_sections(text)
        return relevant_text

    except Exception as e:
        return ""

# -----------------------------------------------------------------------------
# 3. Diff 계산 (텍스트 비교)
# -----------------------------------------------------------------------------
def compare_texts(text1, text2):
    # 전처리
    norm1 = normalize_text(text1)
    norm2 = normalize_text(text2)
    
    # 토큰화 (단어 단위 + 줄바꿈 단위)
    # \n을 하나의 토큰으로 취급하여 리스트 생성
    tokens1 = re.findall(r'\S+|\n', norm1)
    tokens2 = re.findall(r'\S+|\n', norm2)
    
    matcher = difflib.SequenceMatcher(None, tokens1, tokens2)
    
    diff_html_parts = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # 변경 없는 부분
            chunk = tokens1[i1:i2]
            # \n을 <br>로 변환하여 출력
            text_chunk = " ".join(chunk).replace('\n', '<br>')
            # 불필요한 공백 제거 (<br> 앞뒤)
            text_chunk = text_chunk.replace(' <br> ', '<br>').replace('<br> ', '<br>')
            diff_html_parts.append(f'<span style="color: #333;">{text_chunk}</span>')
            
        elif tag == 'replace':
            # 변경: 삭제된 부분(빨강) -> 추가된 부분(초록)
            
            # 1. 삭제된 텍스트
            del_chunk = tokens1[i1:i2]
            del_text = " ".join(del_chunk).replace('\n', '↵<br>') # 줄바꿈 삭제 표시
            diff_html_parts.append(f'<span style="background-color: #ffeef0; color: #b31d28; text-decoration: line-through; padding: 2px 0;">{del_text}</span>')
            
            diff_html_parts.append('<span style="color: #ccc; margin: 0 4px;">▶</span>')
            
            # 2. 추가된 텍스트
            ins_chunk = tokens2[j1:j2]
            ins_text = " ".join(ins_chunk).replace('\n', '↵<br>') # 줄바꿈 추가 표시
            diff_html_parts.append(f'<span style="background-color: #e6ffed; color: #22863a; fontWeight: bold; padding: 2px 0;">{ins_text}</span>')
            
        elif tag == 'delete':
            del_chunk = tokens1[i1:i2]
            del_text = " ".join(del_chunk).replace('\n', '↵<br>')
            diff_html_parts.append(f'<span style="background-color: #ffeef0; color: #b31d28; text-decoration: line-through; padding: 2px 0;">{del_text}</span>')
            
        elif tag == 'insert':
            ins_chunk = tokens2[j1:j2]
            ins_text = " ".join(ins_chunk).replace('\n', '↵<br>')
            diff_html_parts.append(f'<span style="background-color: #e6ffed; color: #22863a; fontWeight: bold; padding: 2px 0;">{ins_text}</span>')
            
        # 가독성을 위한 공백
        diff_html_parts.append(" ")
        
    final_html = "".join(diff_html_parts)
    
    # HTML 가독성 보정 (연속된 br 정리)
    final_html = final_html.replace(' <br>', '<br>').replace('<br> ', '<br>')
    
    return f'<div style="line-height: 1.8; font-size: 16px;">{final_html}</div>'

# -----------------------------------------------------------------------------
# 4. Main UI
# -----------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="스마트 PDF 문서 비교기", layout="wide")
    
    st.title("📄 스마트 PDF 문서 비교기 (Text Ver.)")
    st.markdown("""
    두 개의 PDF 파일을 업로드하면, 서식이나 의미 없는 조사('습니다' 등) 차이는 무시하고 
    **효능·효과, 용법·용량, 사용상의 주의사항** 등 핵심 내용의 변경사항만 텍스트로 보여줍니다.
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
            
            # [디버깅] 추출 내용 확인
            with st.expander("🔍 [디버그] 추출된 텍스트 확인 (섹션이 잘 잡혔는지 확인하세요)"):
                d_col1, d_col2 = st.columns(2)
                d_col1.text_area("File 1 Extracted", text1, height=200)
                d_col2.text_area("File 2 Extracted", text2, height=200)

            # 2. 비교 수행
            if not text1.strip() or not text2.strip():
                st.warning("⚠️ 문서에서 비교할 핵심 섹션(효능, 용법, 주의사항)을 찾지 못했습니다.")
                st.info("문서가 이미지 형태이거나, 해당 섹션 제목이 인식되지 않는 특이한 형식일 수 있습니다.")
            else:
                diff_result = compare_texts(text1, text2)
                
                st.divider()
                st.subheader("📊 비교 결과")
                
                if diff_result:
                    # 결과 출력
                    st.markdown(diff_result, unsafe_allow_html=True)
                else:
                    st.success("✅ 두 문서의 핵심 내용(효능, 용법, 주의사항)이 동일합니다.")
                    st.write("(단순 줄바꿈이나, 의미 없는 조사는 무시되었습니다.)")

if __name__ == "__main__":
    main()
