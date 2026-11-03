"""
ClassCard 초록색 단어 세트 자동 학습 프로그램 (암기 / 리콜 / 스펠 전용)
- 암기학습 (100% 미만일 때만 수행, 100% 이상 시 자동 스킵)
- 리콜학습 (100% 미만일 때만 수행, 100% 이상 시 자동 스킵)
- 스펠학습 (100% 미만일 때만 수행, 100% 이상 시 자동 스킵)
* 테스트 기능: 차후 업데이트를 통해 지원 예정 (현재 암기/리콜/스펠 전용)
* 학생 리포트(/ClassReports) 실시간 분석으로 100% 이상 세부 학습 자동 건너뛰기
"""

import time
import re
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# ────────────────────────────────────────────
# 로깅 설정
# ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ClassCardAuto")

CLASSCARD_URL = "https://www.classcard.net"
DEFAULT_CLASS_URL = "https://www.classcard.net/ClassMain/1954022"


def init_driver() -> webdriver.Chrome:
    """크롬 드라이버 초기화 (안정적인 일반 옵션 + 비밀번호 저장 팝업 비활성화)"""
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    # 비밀번호 저장 팝업 비활성화
    options.add_experimental_option(
        "prefs",
        {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        },
    )
    driver = webdriver.Chrome(options=options)
    return driver


def click_visible_element(driver, selectors, text_keywords=None) -> bool:
    """화면에 실제로 표시된(is_displayed) 요소를 찾아 Selenium 마우스 클릭 및 JS 클릭을 수행"""
    if isinstance(selectors, str):
        selectors = [selectors]
    for sel in selectors:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                if el.is_displayed():
                    if text_keywords:
                        txt = el.text.strip()
                        if not any(k in txt for k in text_keywords):
                            continue
                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                        time.sleep(0.05)
                        ActionChains(driver).move_to_element(el).click().perform()
                        return True
                    except Exception:
                        try:
                            el.click()
                            return True
                        except Exception:
                            driver.execute_script("""
                                ['pointerdown', 'mousedown', 'mouseup', 'click'].forEach(function(t) {
                                    try { arguments[0].dispatchEvent(new MouseEvent(t, {bubbles: true, cancelable: true, view: window})); } catch(e) {}
                                });
                                try { arguments[0].click(); } catch(e) {}
                                if (typeof jQuery !== 'undefined') {
                                    try { jQuery(arguments[0]).trigger('click'); } catch(e) {}
                                }
                            """, el)
                            return True
        except Exception:
            pass
    return False


def safe_click(driver, el):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.15)
        ActionChains(driver).move_to_element(el).click().perform()
    except Exception:
        try:
            el.click()
        except Exception:
            driver.execute_script("arguments[0].click();", el)


# ────────────────────────────────────────────
# 0. 텍스트 정규화 및 사전 구축 유틸리티
# ────────────────────────────────────────────
def normalize_text(text: str) -> str:
    """품사 태그, 특수문자, 불필요한 공백을 제거하여 순수 텍스트로 정규화"""
    if not text:
        return ""
    # 품사 태그 제거: [명], [동], [형], [부], [전], [대] 등
    text = re.sub(r"\[.*?\]", " ", text)
    # 괄호 안의 부가설명 제거 (예: (주로 복수형으로))
    text = re.sub(r"\(.*?\)", " ", text)
    # 특수문자 제거 (~, ·, ㆍ, ,, /, -, \r, \n 등)
    text = re.sub(r"[~·ㆍ,/\r\n\t\-_\'\"]", " ", text)
    # 소문자 및 연속 공백 정리
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def fetch_set_dictionary(driver, set_idx: str, class_id: str) -> dict:
    """세트 페이지에서 전체 단어 데이터를 가져와 양방향 정규화 사전 구축"""
    set_url = f"{CLASSCARD_URL}/set/{set_idx}/{class_id}"
    log.info(f"  [사전 구축] 단어 데이터 로딩: {set_url}")
    driver.get(set_url)
    time.sleep(2)

    # 1. window.study_data 자바스크립트 객체 읽기
    raw_data = driver.execute_script("""
        if (typeof study_data !== 'undefined' && Array.isArray(study_data) && study_data.length > 0) {
            return study_data;
        }
        return null;
    """)

    # 2. 혹시 없을 경우 DOM에서 카드 파싱
    if not raw_data:
        raw_data = driver.execute_script("""
            var list = [];
            document.querySelectorAll('.flip-card, .card-item, .dict-list-item').forEach(function(el) {
                var f = el.querySelector('.front, .word, .ex_front');
                var b = el.querySelector('.back, .meaning, .ex_back');
                var idx = el.getAttribute('data-idx') || '';
                if (f && b) {
                    list.push({
                        card_idx: idx,
                        front: f.innerText.trim(),
                        back: b.innerText.trim()
                    });
                }
            });
            return list;
        """)

    idx_to_card = {}
    front_to_back = {}
    back_to_front = {}
    word_list = []

    if raw_data:
        for item in raw_data:
            c_idx = str(item.get("card_idx", "")).strip()
            front = str(item.get("front", "")).strip()
            back = str(item.get("back", "")).strip()

            if not front and not back:
                continue

            card_info = {"idx": c_idx, "front": front, "back": back}
            word_list.append(card_info)

            if c_idx:
                idx_to_card[c_idx] = card_info

            norm_f = normalize_text(front)
            norm_b = normalize_text(back)

            if norm_f:
                front_to_back[norm_f] = back
            if norm_b:
                back_to_front[norm_b] = front

            # 뜻(back)이 쉼표나 슬래시로 여러 개인 경우 개별 뜻도 매핑
            raw_back_no_pos = re.sub(r"\[.*?\]", "", back)
            for part in re.split(r"[,/\r\n]+", raw_back_no_pos):
                np = normalize_text(part)
                if np and np not in back_to_front:
                    back_to_front[np] = front

    log.info(f"  [사전 구축 완료] 총 {len(word_list)}개 단어 인덱싱 완료")
    return {
        "idx_to_card": idx_to_card,
        "front_to_back": front_to_back,
        "back_to_front": back_to_front,
        "word_list": word_list,
    }


# ────────────────────────────────────────────
# 0-1. 전체 세트별 학습 리포트(진도율) 파싱 - set_idx 키로 직접 매핑
# ────────────────────────────────────────────
def fetch_class_reports(driver, class_id: str) -> dict:
    """학생 리포트 페이지(/ClassReports/users)를 분석하여 모든 세트의 진도율(%)을
    set_idx를 키로 하는 dict로 반환 (제목 매칭 불필요 - 100% 정확)"""
    report_url = f"{CLASSCARD_URL}/ClassReports/users/{class_id}"
    log.info(f"학생 리포트 페이지 분석 중: {report_url}")
    driver.get(report_url)
    time.sleep(2.5)

    # DOM에서 /set/XXXXX 링크를 기준으로 각 패널의 진도율을 추출 (set_idx 키)
    reports = driver.execute_script("""
        var rep = {};
        document.querySelectorAll('a[href*="/set/"]').forEach(function(a) {
            var href = a.getAttribute('href') || '';
            var parts = href.split('/');
            var setIdx = parts[2];
            var panel = a.closest('.class-report-panel') || a.parentElement;
            if (setIdx && panel) {
                var text = panel.innerText;
                var mem = 0, rec = 0, spl = 0;
                var mMem = text.match(/암기학습\\s*(\\d+)%/);
                if (mMem) mem = parseInt(mMem[1]);
                var mRec = text.match(/리콜학습\\s*(\\d+)%/);
                if (mRec) rec = parseInt(mRec[1]);
                var mSpl = text.match(/스펠학습\\s*(\\d+)%/);
                if (mSpl) spl = parseInt(mSpl[1]);
                rep[setIdx] = {
                    set_idx: setIdx,
                    title: a.innerText.trim(),
                    memorize: mem,
                    recall: rec,
                    spell: spl
                };
            }
        });
        return rep;
    """)

    log.info(f"📊 총 {len(reports)}개 세트의 학습 진도율(리포트) 로드 완료")
    for idx, r in list(reports.items())[:3]:
        log.info(f"  예시 - [{idx}] 암기:{r['memorize']}%, 리콜:{r['recall']}%, 스펠:{r['spell']}%")
    return reports


def get_set_progress(set_idx: str, report_dict: dict) -> dict:
    """set_idx로 리포트 진도율 조회 (O(1) 직접 접근, 오매칭 없음)"""
    if not report_dict:
        return {"memorize": 0, "recall": 0, "spell": 0}
    return report_dict.get(str(set_idx), {"memorize": 0, "recall": 0, "spell": 0})


# ────────────────────────────────────────────
# 1. 로그인 (isTrusted 보안 우회)
# ────────────────────────────────────────────
def login(driver, user_id: str, password: str) -> bool:
    log.info(f"ClassCard 로그인 시도 ({user_id})...")
    driver.get(f"{CLASSCARD_URL}/Login")
    time.sleep(2)

    # 직접 AJAX 로그인 호출
    res = driver.execute_async_script("""
        var callback = arguments[arguments.length - 1];
        var id = arguments[0];
        var pw = arguments[1];

        $('.login_id').val(id);
        $('.login_pwd').val(pw);

        jQuery.ajax({
            url: "https://www.classcard.net/LoginProc",
            type: "POST",
            data: $('#loginForm').serialize(),
            dataType: "json",
            success: function(data) {
                if (data.result === 'ok') {
                    applyV2LoginSuccess(data);
                }
                callback(data);
            },
            error: function(err) {
                callback({result: 'error', error: err});
            }
        });
    """, user_id, password)

    log.info(f"로그인 응답: {res.get('result', 'fail') if isinstance(res, dict) else res}")
    time.sleep(2.5)

    if isinstance(res, dict) and res.get("result") == "ok":
        user_name = res.get("name", "")
        log.info(f"✅ 로그인 성공! 환영합니다, {user_name}님")
        return True
    else:
        log.error(f"❌ 로그인 실패: {res}")
        return False


# ────────────────────────────────────────────
# 2. 초록색 '단어' 세트 수집
# ────────────────────────────────────────────
def collect_green_sets(driver, class_url: str) -> list:
    class_url = class_url.strip().strip("[]'\"").strip()
    log.info(f"클래스 페이지 이동: {class_url}")
    driver.get(class_url)
    time.sleep(3)

    sets = driver.execute_script("""
        var result = [];
        var rows = document.querySelectorAll('.set-items[data-idx]');
        rows.forEach(function(row) {
            if (row.querySelector('.set-icon.word')) {
                var idx = row.getAttribute('data-idx');
                var nameEl = row.querySelector('.set-name-a');
                var title = nameEl ? nameEl.innerText.trim() : '이름 없음';
                title = title.replace(/\\s+/g, ' ');
                result.push({
                    idx: idx,
                    title: title
                });
            }
        });
        return result;
    """)

    class_id = class_url.rstrip("/").split("/")[-1]
    final_list = []
    for s in sets:
        url = f"{CLASSCARD_URL}/set/{s['idx']}/{class_id}"
        final_list.append({
            "idx": s["idx"],
            "title": s["title"],
            "url": url,
            "class_id": class_id
        })

    log.info(f"초록색 '단어' 세트 총 {len(final_list)}개 발견")
    for idx, s in enumerate(final_list, 1):
        log.info(f"  {idx:2d}. {s['title'][:50]} (ID: {s['idx']})")

    return final_list


# ────────────────────────────────────────────
# 3. 암기 학습 자동화 (200% 미만일 때 수행)
# ────────────────────────────────────────────
def js_key_event(driver, key_code: int, shift=False):
    """포커스 없이 JS로 키보드 이벤트를 발생시킨다 (백그라운드 창에서도 동작)"""
    driver.execute_script(f"""
        var opts = {{
            key: arguments[0], keyCode: arguments[1], which: arguments[1],
            shiftKey: {'true' if shift else 'false'}, bubbles: true, cancelable: true
        }};
        var el = document.activeElement || document.body;
        el.dispatchEvent(new KeyboardEvent('keydown', opts));
        el.dispatchEvent(new KeyboardEvent('keypress', opts));
        el.dispatchEvent(new KeyboardEvent('keyup', opts));
    """, " " if key_code == 32 else str(chr(key_code)), key_code)


def js_click(driver, selector: str) -> bool:
    """CSS 셀렉터로 보이는 첫 번째 요소를 JS로 강력하게 클릭 (마우스 이벤트 풀세트 발생)"""
    return driver.execute_script(f"""
        var els = document.querySelectorAll('{selector}');
        for (var el of els) {{
            if (el.offsetParent !== null || el.offsetWidth > 0 || el.offsetHeight > 0) {{
                ['pointerdown', 'mousedown', 'mouseup', 'click'].forEach(function(t) {{
                    try {{ el.dispatchEvent(new MouseEvent(t, {{bubbles: true, cancelable: true, view: window}})); }} catch(e) {{}}
                }});
                try {{ el.click(); }} catch(e) {{}}
                if (typeof jQuery !== 'undefined') {{
                    try {{ jQuery(el).trigger('click'); }} catch(e) {{}}
                }}
                return true;
            }}
        }}
        return false;
    """)


def select_recall_answer(driver, ans_n: int):
    """리콜 퀴즈에서 정답 선택지를 5중으로 선택 (숫자키 JS/Selenium + DOM 마우스 이벤트 풀세트 + ActionChains)"""
    num_str = str(ans_n)
    key_code = 48 + ans_n  # '1'=49, '2'=50, '3'=51, '4'=52

    # 1. JS 전역 숫자키 이벤트 (백그라운드 창에서도 동작 보장)
    driver.execute_script("""
        var numStr = arguments[0];
        var keyCode = arguments[1];
        ['keydown', 'keypress', 'keyup'].forEach(function(t) {
            var ev = new KeyboardEvent(t, {
                key: numStr, code: 'Digit' + numStr, keyCode: keyCode, which: keyCode,
                bubbles: true, cancelable: true
            });
            document.dispatchEvent(ev);
            window.dispatchEvent(ev);
            if (document.activeElement) document.activeElement.dispatchEvent(ev);
        });
    """, num_str, key_code)

    # 2. JS DOM 선택지 마우스 이벤트 발생 (타겟, 부모, 자식 및 jQuery 클릭)
    driver.execute_script("""
        var ans_n = arguments[0];
        var card = document.querySelector('.CardItem.current') || document.querySelector('.CardItem.showing');
        if (!card) return;

        // 선택지 탐색: .answer 클래스 우선
        var ans = card.querySelector('[class*="cmFkaW8"].answer, .answer');

        // 선택지 목록 탐색 (라디오, 버튼, 리스트 아이템 등 폭넓게 검색)
        var selectors = [
            '[class*="cmFkaW8"]', '.btn-choice', '.list-item', '.choice-item',
            '.choice', 'li[role="button"]', 'ul li', 'ol li', '.item'
        ];
        var items = [];
        for (var sel of selectors) {
            var found = Array.from(card.querySelectorAll(sel)).filter(function(el) {
                return (el.offsetParent !== null || el.offsetWidth > 0) && el.innerText.trim().length > 0;
            });
            if (found.length >= 4) {
                items = found;
                break;
            }
            if (found.length > items.length) items = found;
        }

        var target = ans || (items.length >= ans_n ? items[ans_n - 1] : null);
        if (target) {
            var toClick = [target];
            if (target.parentElement) toClick.push(target.parentElement);
            var child = target.querySelector('input, label, a, span');
            if (child) toClick.push(child);

            toClick.forEach(function(el) {
                ['pointerdown', 'mousedown', 'mouseup', 'click'].forEach(function(etype) {
                    try {
                        el.dispatchEvent(new MouseEvent(etype, {bubbles: true, cancelable: true, view: window}));
                    } catch(e) {}
                });
                try { el.click(); } catch(e) {}
                if (typeof jQuery !== 'undefined') {
                    try { jQuery(el).trigger('click'); } catch(e) {}
                }
            });
        }
    """, ans_n)

    # 3. Selenium ActionChains 키보드 숫자 전송 (포커스 상태 지원)
    try:
        ActionChains(driver).send_keys(num_str).perform()
    except Exception:
        pass

    # 4. Selenium ActionChains 마우스 실제 클릭
    try:
        cards = driver.find_elements(By.CSS_SELECTOR, ".CardItem.current, .CardItem.showing")
        if cards:
            c = cards[0]
            answers = [el for el in c.find_elements(By.CSS_SELECTOR, ".answer, [class*='cmFkaW8'].answer") if el.is_displayed()]
            if answers:
                ActionChains(driver).move_to_element(answers[0]).click().perform()
            else:
                choices = [el for el in c.find_elements(By.CSS_SELECTOR, "[class*='cmFkaW8'], .btn-choice, li") if el.is_displayed()]
                if choices and 1 <= ans_n <= len(choices):
                    ActionChains(driver).move_to_element(choices[ans_n - 1]).click().perform()
    except Exception:
        pass


def click_spell_confirm_button(driver) -> bool:
    """스펠 화면 하단의 보라색 [확인] (ENTER) 버튼 또는 제출 버튼을 강력하게 찾아 클릭"""
    return driver.execute_script("""
        // 1. 전용 클래스 및 주요 셀렉터 탐색
        var selectors = [
            '.btn-submit', '.btn-confirm', '.btn-check', '.btn-short-submit',
            '.study-bottom a', '.study-bottom button', '.study-bottom .btn',
            'button.btn-primary', 'a.btn-primary', '.btn-xl', '.btn-answer'
        ];
        for (var sel of selectors) {
            var el = document.querySelector(sel);
            if (el && (el.offsetParent !== null || el.offsetWidth > 0)) {
                el.click();
                return true;
            }
        }
        // 2. 텍스트가 '확인' 또는 'ENTER'인 가시적 요소 탐색 (보라색 확인 버튼 타겟팅)
        var all = Array.from(document.querySelectorAll('button, a, div[role="button"], span[role="button"], .btn'));
        for (var b of all) {
            if (b.offsetParent !== null || b.offsetWidth > 0) {
                var t = b.innerText.trim();
                if (t === '확인' || t.startsWith('확인') || t === 'ENTER' || t.includes('ENTER') || t.includes('제출')) {
                    b.click();
                    return true;
                }
            }
        }
        return false;
    """)


def submit_spell_answer(driver, text: str):
    """입력창에 단어 입력 후 Enter 및 보라색 [확인] 버튼 클릭 (5중 전송 보장)"""
    # 1. Selenium으로 직접 입력 및 엔터 시도 (포커스 상태일 때 가장 확실)
    try:
        cards = driver.find_elements(By.CSS_SELECTOR, ".CardItem.current")
        if cards:
            inps = cards[0].find_elements(By.CSS_SELECTOR, 'input[name="input_answer"], input[placeholder*="단어"], input[type="text"]')
            vis_inps = [i for i in inps if i.is_displayed()]
            if vis_inps:
                inp = vis_inps[0]
                inp.click()
                inp.clear()
                inp.send_keys(text)
                time.sleep(0.05)
                inp.send_keys(Keys.ENTER)
    except Exception:
        pass

    # 2. JS로 DOM 값 설정 및 input, change 이벤트 발생 (백그라운드 지원)
    driver.execute_script("""
        var text = arguments[0];
        var card = document.querySelector('.CardItem.current');
        if (!card) return;
        var inps = Array.from(card.querySelectorAll(
            'input[name="input_answer"], input[placeholder*="단어"], input[type="text"]'
        ));
        var inp = inps.find(function(i) { return i.offsetParent !== null || i.offsetWidth > 0; });
        if (!inp) return;
        inp.focus();

        // React/Vue/네이티브 setter 동기화
        try {
            var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeSetter.call(inp, text);
        } catch(e) {}
        inp.value = text;
        inp.dispatchEvent(new Event('input', {bubbles: true}));
        inp.dispatchEvent(new Event('change', {bubbles: true}));

        // jQuery 지원
        if (typeof jQuery !== 'undefined') {
            try {
                jQuery(inp).val(text).trigger('input').trigger('change');
                var e = jQuery.Event('keydown', {which: 13, keyCode: 13});
                jQuery(inp).trigger(e);
            } catch(e) {}
        }

        // input, document, window 전역 Enter 이벤트 전달
        ['keydown', 'keypress', 'keyup'].forEach(function(t) {
            var ev = new KeyboardEvent(t, {
                key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true
            });
            inp.dispatchEvent(ev);
            document.dispatchEvent(ev);
            window.dispatchEvent(ev);
        });
    """, text)

    time.sleep(0.1)

    # 3. 보라색 [확인] (ENTER) 버튼 직접 JS 클릭
    click_spell_confirm_button(driver)

    # 4. ActionChains 키보드 엔터 전송
    try:
        ActionChains(driver).send_keys(Keys.ENTER).perform()
    except Exception:
        pass


def auto_memorize(driver, set_idx: str, class_id: str, set_title: str):
    log.info(f"  ▶ [암기 학습] 시작: {set_title[:30]}")
    set_url = f"{CLASSCARD_URL}/set/{set_idx}/{class_id}"

    for section in range(1, 10):
        mem_url = f"{CLASSCARD_URL}/Memorize/{set_idx}/{section}/{class_id}"
        driver.get(mem_url)
        time.sleep(2.5)

        if "ClassMain" in driver.current_url or "/set/" in driver.current_url:
            break

        # [암기 학습 시작] 팝업 버튼 JS 클릭
        for _ in range(8):
            clicked = js_click(driver, '.btn-opt-start') or \
                      js_click(driver, '.btn-start') or \
                      click_visible_element(driver,
                          ['a.btn-primary', 'button.btn-primary', '.modal-footer .btn'],
                          ['시작', '확인', '학습'])
            if clicked:
                time.sleep(0.3)
                break
            time.sleep(0.5)
        time.sleep(1.5)

        log.info(f"    - {section}구간 카드 암기 진행 중...")

        for step in range(300):
            time.sleep(0.2)

            # 1. 구간 완료 팝업 처리
            is_done = driver.execute_script("""
                var endText = document.querySelector('.study-end-text, .end-study');
                if (endText && (endText.offsetParent !== null || endText.offsetWidth > 0)) return true;
                var t = document.body.innerText;
                return t.includes('구간 학습이 완료되었습니다') ||
                       t.includes('GOOD JOB') ||
                       t.includes('학습이 완료되었습니다');
            """)
            if is_done:
                js_click(driver, '.btn-next-section') or \
                    js_click(driver, '.btn-complete') or \
                    js_click(driver, '.btn-confirm') or \
                    click_visible_element(driver,
                        ['.modal-footer .btn', 'a.btn-primary', 'button.btn-primary'],
                        ['다음', '확인', '완료'])
                log.info(f"    - {section}구간 완료!")
                break

            # 2. "이제 알아요" 버튼 JS 클릭
            know_clicked = (
                js_click(driver, '.btn-short-change-card') or
                js_click(driver, '.btn-know') or
                js_click(driver, '.btn-know-box a')
            )

            if know_clicked:
                # Shift+Space JS 이벤트 (백업)
                driver.execute_script("""
                    var el = document.activeElement || document.body;
                    ['keydown','keyup'].forEach(function(t) {
                        el.dispatchEvent(new KeyboardEvent(t, {
                            key:' ', keyCode:32, which:32, shiftKey:true, bubbles:true
                        }));
                    });
                """)
                log.info(f"    step {step+1}: [이제 알아요] 버튼 클릭")
                time.sleep(0.8)
            else:
                # 카드 뒤집기 JS 클릭 + Space 이벤트
                flipped = (
                    js_click(driver, '.CardItem.current .card-cover') or
                    js_click(driver, '.CardItem.current .front') or
                    js_click(driver, '.CardItem.current')
                )
                driver.execute_script("""
                    var el = document.activeElement || document.body;
                    ['keydown','keypress','keyup'].forEach(function(t) {
                        el.dispatchEvent(new KeyboardEvent(t, {
                            key:' ', keyCode:32, which:32, bubbles:true, cancelable:true
                        }));
                    });
                """)
                log.info(f"    step {step+1}: 카드 뒤집기 (JS Space)")
                time.sleep(0.6)

        time.sleep(1)

    log.info("  ✅ [암기 학습] 완료")
    driver.get(set_url)
    time.sleep(2)


# ────────────────────────────────────────────
# 4. 리콜 학습 자동화 (200% 미만일 때 수행)
# ────────────────────────────────────────────
def auto_recall(driver, set_idx: str, class_id: str, set_title: str, set_dict: dict = None):
    log.info(f"  ▶ [리콜 학습] 시작: {set_title[:30]}")
    set_url = f"{CLASSCARD_URL}/set/{set_idx}/{class_id}"

    for section in range(1, 10):
        rec_url = f"{CLASSCARD_URL}/Recall/{set_idx}/{section}/{class_id}"
        driver.get(rec_url)
        time.sleep(2.5)

        if "ClassMain" in driver.current_url or "/set/" in driver.current_url:
            break

        # [리콜 학습 시작] 팝업 버튼 JS 클릭
        for _ in range(8):
            clicked = js_click(driver, '.btn-opt-start') or \
                      js_click(driver, '.btn-start') or \
                      click_visible_element(driver,
                          ['a.btn-primary', 'button.btn-primary', '.modal-footer .btn'],
                          ['시작', '확인', '학습'])
            if clicked:
                time.sleep(0.3)
                break
            time.sleep(0.5)
        time.sleep(1.5)

        log.info(f"    - {section}구간 리콜 퀴즈 푸는 중...")
        last_card_idx = None
        last_ans_n = None
        same_card_count = 0

        for step in range(200):
            time.sleep(0.2)

            # 1. 구간 완료 확인
            is_done = driver.execute_script("""
                var t = document.body.innerText;
                var endText = document.querySelector('.study-end-text, .end-study');
                if (endText && (endText.offsetParent !== null || endText.offsetWidth > 0)) return true;
                return t.includes('구간 학습이 완료되었습니다') ||
                       t.includes('GOOD JOB') ||
                       t.includes('학습이 완료되었습니다');
            """)
            if is_done:
                js_click(driver, '.btn-next-section') or \
                    js_click(driver, '.btn-complete') or \
                    js_click(driver, '.btn-confirm') or \
                    click_visible_element(driver,
                        ['.modal-footer .btn', 'a.btn-primary', 'button.btn-primary'],
                        ['다음', '확인', '완료'])
                log.info(f"    - {section}구간 완료!")
                break

            # 2. 현재 활성 카드 식별 및 중복 입력 방지
            card_info = driver.execute_script("""
                var card = document.querySelector('.CardItem.current') || document.querySelector('.CardItem.showing');
                if (!card) return null;
                return { idx: card.getAttribute('data-idx') };
            """)

            if card_info:
                c_idx = card_info.get("idx")
                if c_idx and c_idx == last_card_idx:
                    same_card_count += 1
                    if same_card_count >= 2:
                        retry_ans = last_ans_n or 1
                        log.info(f"    step {step+1}: [카드 {c_idx} 전환 대기/재시도 {same_card_count}] 선택지 {retry_ans}번 재전송")
                        select_recall_answer(driver, retry_ans)
                        time.sleep(0.6)
                        if same_card_count >= 5:
                            log.info(f"    step {step+1}: [강제 전환] SPACE 전송")
                            js_key_event(driver, 32)
                            same_card_count = 0
                            last_card_idx = None
                            last_ans_n = None
                            time.sleep(1.0)
                        continue
                    time.sleep(0.4)
                    continue
                else:
                    same_card_count = 0
            else:
                c_idx = None

            # 3. 정답 번호 계산
            # 1순위: DOM에 .answer 클래스가 붙어있는 정답 번호 찾기
            answer_num = driver.execute_script("""
                var card = document.querySelector('.CardItem.current') || document.querySelector('.CardItem.showing');
                if (!card) return null;
                var items = Array.from(card.querySelectorAll('[class*="cmFkaW8"], .btn-choice, .list-item, li')).filter(function(el) {
                    return (el.offsetParent !== null || el.offsetWidth > 0) && el.innerText.trim().length > 0;
                });
                if (items.length === 0) return null;
                for (var i = 0; i < items.length; i++) {
                    if (items[i].classList.contains('answer')) return i + 1;
                }
                return null;
            """)

            # 2순위: 사전 매칭으로 정답 계산
            if not answer_num and set_dict:
                card_data = driver.execute_script("""
                    var card = document.querySelector('.CardItem.current') || document.querySelector('.CardItem.showing');
                    if (!card) return null;
                    var qEl = card.querySelector('.question, .exam-question, .front, .back, .card-body');
                    var qText = qEl ? qEl.innerText.trim() : '';
                    var items = Array.from(card.querySelectorAll('[class*="cmFkaW8"], .btn-choice, .list-item, li')).filter(function(el) {
                        return (el.offsetParent !== null || el.offsetWidth > 0) && el.innerText.trim().length > 0;
                    });
                    return { qText: qText, choices: items.map(function(el, i) { return { idx: i+1, text: el.innerText.trim() }; }) };
                """)
                if isinstance(card_data, dict) and card_data.get("choices"):
                    norm_q = normalize_text(card_data.get("qText", ""))
                    expected = set_dict["front_to_back"].get(norm_q) or set_dict["back_to_front"].get(norm_q)
                    norm_exp = normalize_text(expected) if expected else ""
                    best_c = None
                    for c in card_data["choices"]:
                        nc = normalize_text(c["text"])
                        if nc == norm_exp or (norm_exp and (nc in norm_exp or norm_exp in nc)):
                            best_c = c["idx"]
                            break
                    answer_num = best_c if isinstance(best_c, int) else None

            # dict 타입 안전장치
            if isinstance(answer_num, dict):
                answer_num = None

            # 4. 정답 선택지 강력 5중 선택 (JS 숫자키 + DOM 마우스 이벤트 + Selenium)
            if isinstance(answer_num, int) and answer_num >= 1:
                ans_n = int(answer_num)
                select_recall_answer(driver, ans_n)
                log.info(f"    step {step+1}: 정답 선택지 {ans_n}번 자동 선택 (카드 {c_idx})")
                last_card_idx = c_idx
                last_ans_n = ans_n
                same_card_count = 0
                time.sleep(1.2)
            else:
                # 선택지 번호 특정 실패 시 1번 시도 후 Space
                select_recall_answer(driver, 1)
                js_key_event(driver, 32)
                time.sleep(0.5)

        time.sleep(1)

    log.info("  ✅ [리콜 학습] 완료")
    driver.get(set_url)
    time.sleep(2)


# ────────────────────────────────────────────
# 5. 스펠 학습 자동화 (200% 미만일 때 수행)
# ────────────────────────────────────────────
def auto_spell(driver, set_idx: str, class_id: str, set_title: str, set_dict: dict):
    """스펠학습 자동화 - 화면 DOM의 study_data JS 변수에서 정답을 직접 추출하여 입력"""
    log.info(f"  ▶ [스펠 학습] 시작: {set_title[:30]}")
    set_url = f"{CLASSCARD_URL}/set/{set_idx}/{class_id}"

    for section in range(1, 10):
        spell_url = f"{CLASSCARD_URL}/Spell/{set_idx}/{section}/{class_id}"
        driver.get(spell_url)
        time.sleep(2.5)

        if "ClassMain" in driver.current_url or "/set/" in driver.current_url:
            log.info(f"    - {section}구간 없음, 스펠 학습 종료")
            break

        # ── 스펠 화면에서 study_data JS 변수로 카드별 정답 사전 구축 ──
        # (set_dict의 idx_to_card보다 현재 페이지의 study_data가 더 정확)
        spell_study_data = driver.execute_script("""
            try {
                if (typeof study_data !== 'undefined' && Array.isArray(study_data)) {
                    return study_data.map(function(d) {
                        return {
                            card_idx: String(d.card_idx || d.idx || ''),
                            front: String(d.front || d.word || d.spell || ''),
                            back: String(d.back || d.meaning || d.desc || '')
                        };
                    });
                }
            } catch(e) {}
            return null;
        """)

        # study_data → {card_idx: front_word} 빠른 조회 사전
        spell_idx_map = {}
        if spell_study_data:
            for item in spell_study_data:
                ci = str(item.get("card_idx", "")).strip()
                fw = str(item.get("front", "")).strip()
                if ci and fw:
                    spell_idx_map[ci] = fw
            log.info(f"    - {section}구간: study_data {len(spell_idx_map)}개 카드 사전 구축")
        else:
            log.info(f"    - {section}구간: study_data 없음, set_dict 폴백 사용")

        # [스펠 학습 시작] 팝업 버튼 JS 클릭
        for _ in range(8):
            clicked = js_click(driver, '.btn-opt-start') or \
                      js_click(driver, '.btn-start') or \
                      click_visible_element(driver,
                          ['a.btn-primary', 'button.btn-primary', '.modal-footer .btn'],
                          ['시작', '확인', '학습'])
            if clicked:
                time.sleep(0.3)
                break
            time.sleep(0.5)
        time.sleep(1.5)

        log.info(f"    - {section}구간 스펠 학습 진행 중...")
        last_card_idx = None
        same_card_count = 0

        for step in range(300):
            time.sleep(0.2)

            # 1. 구간 완료 확인
            is_done = driver.execute_script("""
                var endText = document.querySelector('.study-end-text, .end-study');
                if (endText && endText.offsetParent !== null) return true;
                var t = document.body.innerText;
                return t.includes('구간 학습이 완료되었습니다') ||
                       t.includes('GOOD JOB') ||
                       t.includes('학습이 완료되었습니다');
            """)
            if is_done:
                # 완료 팝업 처리
                js_click(driver, '.btn-next-section') or \
                    js_click(driver, '.btn-complete') or \
                    js_click(driver, '.btn-confirm') or \
                    click_visible_element(driver,
                        ['.modal-footer .btn', 'a.btn-primary', 'button.btn-primary'],
                        ['다음', '확인', '완료'])
                log.info(f"    - {section}구간 완료!")
                break

            # 2. 오답/재도전 화면 감지 → JS SPACE로 탈출
            is_try_again = driver.execute_script("""
                var t = document.body.innerText;
                if (t.includes('나중에 한번 더') || t.includes('Try again')) return true;
                var deactive = document.querySelector('.CardItem.deactive');
                if (deactive && deactive.offsetParent !== null) return true;
                return false;
            """)
            if is_try_again:
                log.info(f"    step {step+1}: [오답] 나중에 한번 더 → JS SPACE 탈출")
                clicked = (
                    js_click(driver, '.btn-short-change-next') or
                    js_click(driver, '.btn-next-box a') or
                    js_click(driver, '.study-bottom.down a') or
                    js_click(driver, 'a.btn-default') or
                    click_spell_confirm_button(driver)
                )
                if not clicked:
                    driver.execute_script("""
                        var el = document.activeElement || document.body;
                        ['keydown','keypress','keyup'].forEach(function(t) {
                            el.dispatchEvent(new KeyboardEvent(t, {
                                key:' ', keyCode:32, which:32, bubbles:true, cancelable:true
                            }));
                        });
                    """)
                last_card_idx = None
                same_card_count = 0
                time.sleep(1.2)
                continue

            # 3. 현재 활성 카드 정보 + 입력창 확인
            card_info = driver.execute_script("""
                var card = document.querySelector('.CardItem.current');
                if (!card) return null;

                var cIdx = card.getAttribute('data-idx') || card.getAttribute('data-card-idx') || '';

                // 화면에 노출된 정답 배지 (오답 후 정답 표시)
                var exposedAnswer = null;
                var ansSelectors = [
                    '.spell-answer', '.label-answer', '.answer-text',
                    '.label-success', '.correct-answer', '.badge-answer'
                ];
                for (var s of ansSelectors) {
                    var el = card.querySelector(s);
                    if (el && el.offsetParent !== null) {
                        var t = el.innerText.replace(/정답|answer/gi, '').trim();
                        if (t.length > 0) { exposedAnswer = t; break; }
                    }
                }

                // data 속성에서 직접 정답 추출
                var dataFront = card.getAttribute('data-front') ||
                                card.getAttribute('data-spell') ||
                                card.getAttribute('data-word') || null;

                // 질문 텍스트 (한국어 뜻)
                var qEl = card.querySelector(
                    '.spell-content, .back-text, .meaning-text, .card-back, .font-22, .text-center'
                );
                var questionText = qEl ? qEl.innerText.trim() : '';

                // 가시적 입력창
                var inps = Array.from(card.querySelectorAll(
                    'input[name="input_answer"], input[placeholder*="단어"], input[type="text"]'
                ));
                var visibleInp = inps.find(function(i) { return i.offsetParent !== null; });

                return {
                    cardIdx: cIdx,
                    exposedAnswer: exposedAnswer,
                    dataFront: dataFront,
                    questionText: questionText,
                    hasInp: !!visibleInp,
                    inpValue: visibleInp ? visibleInp.value : ''
                };
            """)

            if not card_info:
                time.sleep(0.4)
                continue

            card_idx = str(card_info.get("cardIdx", "")).strip()
            exposed   = card_info.get("exposedAnswer")
            data_front = card_info.get("dataFront")
            q_text    = card_info.get("questionText", "")
            has_inp   = card_info.get("hasInp", False)
            inp_value = card_info.get("inpValue", "")

            # 중복 입력 방지 및 지연 시 보라색 [확인]/Enter 재시도
            if card_idx and card_idx == last_card_idx:
                same_card_count += 1
                if same_card_count >= 2:
                    log.info(f"    step {step+1}: [카드 {card_idx} 대기 {same_card_count}] 보라색 [확인]/Enter 재전송")
                    click_spell_confirm_button(driver)
                    try:
                        ActionChains(driver).send_keys(Keys.ENTER).perform()
                    except Exception:
                        pass
                    time.sleep(0.8)
                    if same_card_count >= 5:
                        log.info(f"    step {step+1}: [강제 전환] SPACE 전송")
                        js_key_event(driver, 32)
                        same_card_count = 0
                        last_card_idx = None
                        time.sleep(1.0)
                    continue
                else:
                    time.sleep(0.4)
                    continue
            else:
                same_card_count = 0

            # ── 정답 우선순위 결정 ──
            # 1순위: 스펠 페이지 study_data (현재 페이지 기준, 가장 정확)
            target_word = spell_idx_map.get(card_idx) if card_idx else None

            # 2순위: set_dict idx_to_card (사전 구축 시 로딩)
            if not target_word and card_idx and card_idx in set_dict["idx_to_card"]:
                target_word = set_dict["idx_to_card"][card_idx]["front"]

            # 3순위: DOM에 노출된 정답 배지
            if not target_word and exposed:
                target_word = exposed

            # 4순위: data-front / data-spell / data-word 속성
            if not target_word and data_front and re.match(r"^[a-zA-Z\s'\-]+$", data_front):
                target_word = data_front

            # 5순위: 한국어 뜻(back)으로 사전 역조회
            if not target_word and q_text:
                norm_q = normalize_text(q_text)
                target_word = set_dict["back_to_front"].get(norm_q)
                if not target_word:
                    for k, v in set_dict["back_to_front"].items():
                        if k and len(k) > 1 and (k in norm_q or norm_q in k):
                            target_word = v
                            break

            # 4. 입력창에 정답 입력 및 보라색 [확인]/Enter 전송 (5중 보장)
            if target_word and has_inp:
                submit_spell_answer(driver, target_word)
                log.info(f"    step {step+1}: '{target_word}' 입력 → [확인]/Enter (카드idx={card_idx})")
                last_card_idx = card_idx
                same_card_count = 0
                time.sleep(1.3)

            elif has_inp and not target_word:
                # 정답 못 찾음 → 확인 버튼 클릭 및 Enter 스킵 시도
                click_spell_confirm_button(driver)
                try:
                    ActionChains(driver).send_keys(Keys.ENTER).perform()
                except Exception:
                    pass
                js_key_event(driver, 13)
                log.info(f"    step {step+1}: ❓정답 미발견 Enter 스킵 (카드idx={card_idx}, q='{q_text[:20]}')")
                last_card_idx = card_idx
                same_card_count = 0
                time.sleep(0.8)
            else:
                # 입력창 없음 (전환 애니메이션 중)
                time.sleep(0.3)

        time.sleep(1.5)

    log.info("  ✅ [스펠 학습] 완료")
    driver.get(set_url)
    time.sleep(2)


# ────────────────────────────────────────────
# 메인 함수
# ────────────────────────────────────────────
def main():
    print("=" * 65)
    print("       ClassCard 초록색 단어 세트 자동 학습기")
    print("       (암기 / 리콜 / 스펠 자동화 - 100% 이상 자동 스킵)")
    print("=" * 65)
    print()
    print(" [ 📖 프로그램 사용 안내 ]")
    print(" 1. ClassCard 로그인 후 입력하신 클래스의 모든 초록색 '단어' 세트를 자동 학습합니다.")
    print(" 2. 학습 순서: 암기 학습 ➔ 리콜 학습 ➔ 스펠 학습")
    print(" 3. 학생 리포트 분석: 각 학습별 진도율이 100% 이상이면 자동으로 건너뜁니다.")
    print(" 4. 백그라운드 지원: 다른 창을 띄워 작업하셔도 브라우저 내부 스크립트로 동작합니다.")
    print()
    print(" 📢 [안내]")
    print("  * 테스트(Test) 기능은 차후 업데이트를 통해 진행될 예정입니다.")
    print("  * 원활한 자동화를 위해 학습 도중 크롬 창을 최소화하거나 닫지 마세요.")
    print("    (다른 창 뒤에 두거나 포커스를 벗어나는 것은 정상 작동합니다)")
    print("=" * 65)
    print()
    input("위 사용법을 확인하셨으면 [Enter] 키를 눌러 로그인을 진행하세요...")
    print()

    # 아이디 입력
    while True:
        user_id = input("ClassCard 아이디(이메일 또는 ID): ").strip()
        if user_id:
            break
        print("⚠️ 아이디를 입력해주세요.")

    # 비밀번호 입력
    while True:
        password = input("ClassCard 비밀번호: ").strip()
        if password:
            break
        print("⚠️ 비밀번호를 입력해주세요.")

    # 클래스 URL 입력 (Enter 시 기본 예시 URL 자동 사용)
    raw_url = input(f"클래스 메인 URL [Enter 누르면 {DEFAULT_CLASS_URL}]: ").strip()
    class_url = raw_url if raw_url else DEFAULT_CLASS_URL
    if not class_url.startswith("http"):
        class_url = "https://" + class_url.lstrip("/")

    print()
    log.info("크롬 브라우저 실행 중...")
    driver = init_driver()

    try:
        # 1. 로그인
        if not login(driver, user_id, password):
            print("\n❌ 로그인에 실패했습니다. 아이디와 비밀번호를 확인해주세요.")
            input("종료하려면 Enter를 누르세요...")
            return

        # 2. 학생 리포트 분석 (전체 세트 진도율 로드)
        class_id = class_url.rstrip("/").split("/")[-1]
        class_reports = fetch_class_reports(driver, class_id)

        # 3. 초록색 단어 세트 수집
        sets = collect_green_sets(driver, class_url)
        if not sets:
            print("\n❌ 초록색 단어 세트를 찾지 못했습니다.")
            input("종료하려면 Enter를 누르세요...")
            return

        print(f"\n발견된 세트 목록 ({len(sets)}개):")
        for i, s in enumerate(sets, 1):
            prog = get_set_progress(s["idx"], class_reports)
            m_p, r_p, s_p = prog.get("memorize", 0), prog.get("recall", 0), prog.get("spell", 0)
            print(f"  {i:2d}. {s['title'][:40]:<40} [암기:{m_p}% | 리콜:{r_p}% | 스펠:{s_p}%]")

        print()
        ans = input("학습을 자동으로 진행하시겠습니까? (100% 이상인 학습은 스킵됩니다) (y/n) [y]: ").strip().lower()
        if ans and ans != "y":
            print("작업이 취소되었습니다.")
            return

        # 4. 각 세트별 암기, 리콜, 스펠 진행
        for i, s in enumerate(sets, 1):
            print("\n" + "=" * 60)
            log.info(f"[{i}/{len(sets)}] 세트 진행 시작: {s['title']}")
            print("=" * 60)

            set_idx = s["idx"]

            try:
                # 세트 시작 전 전체 단어 사전 구축
                set_dict = fetch_set_dictionary(driver, set_idx, class_id)

                # 현재 세트의 리포트 진도율 조회
                prog = get_set_progress(set_idx, class_reports)
                mem_rate = prog.get("memorize", 0)
                rec_rate = prog.get("recall", 0)
                spl_rate = prog.get("spell", 0)

                log.info(f"📊 [{s['title']}] 현재 진도율 - 암기: {mem_rate}%, 리콜: {rec_rate}%, 스펠: {spl_rate}%")

                # 1. 암기학습 (100% 이상이면 스킵 - 이미 완료된 항목)
                if mem_rate >= 100:
                    log.info(f"  ⏭ [암기학습 스킵] 진도율 {mem_rate}% (100% 이상이므로 생략)")
                else:
                    auto_memorize(driver, set_idx, class_id, s["title"])

                # 2. 리콜학습 (100% 이상이면 스킵)
                if rec_rate >= 100:
                    log.info(f"  ⏭ [리콜학습 스킵] 진도율 {rec_rate}% (100% 이상이므로 생략)")
                else:
                    auto_recall(driver, set_idx, class_id, s["title"], set_dict)

                # 3. 스펠학습 (100% 이상이면 스킵)
                if spl_rate >= 100:
                    log.info(f"  ⏭ [스펠학습 스킵] 진도율 {spl_rate}% (100% 이상이므로 생략)")
                else:
                    auto_spell(driver, set_idx, class_id, s["title"], set_dict)

                log.info(f"🎉 [{i}/{len(sets)}] 세트 완료 (암기/리콜/스펠): {s['title']}")

            except Exception as e:
                log.error(f"세트 진행 중 오류 발생 ({s['title']}): {e}")
                import traceback
                traceback.print_exc()

        print("\n" + "=" * 60)
        print("   🎊 모든 초록색 단어 세트의 암기/리콜/스펠 학습이 완료되었습니다! 🎊")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n사용자에 의해 작업이 중단되었습니다.")
    except Exception as e:
        log.error(f"예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()
    finally:
        input("\n종료하려면 Enter를 누르세요...")
        driver.quit()


if __name__ == "__main__":
    main()
