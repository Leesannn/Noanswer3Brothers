"""자격제도안내(licenseInfo{Grade}.kspo) 파싱.

체육지도자 결격사유는 9개 등급 모두 동일한 법조문이라 등급별로 반복 저장하지
않고, 크롤링한 값 중 하나를 공통 텍스트로 한 번만 저장한다.
"""
from bs4 import BeautifulSoup

from .kspo_client import fetch
from .kspo_grades import GRADE_NAMES, license_info_url


def _text(node):
    if node is None:
        return ''
    for br in node.find_all('br'):
        br.replace_with('\n')
    return '\n'.join(line.strip() for line in node.get_text().split('\n') if line.strip())


def _find_section(soup, tab_text_prefix):
    for block in soup.select('div.cptSystemInfo'):
        tab = block.select_one('.tabTxt')
        if tab and tab.get_text(strip=True).startswith(tab_text_prefix):
            return block
    return None


def _numbered_items(section):
    """'.comInfoList li.number' 블록을 {label: [bullet, ...]} 형태로 모은다."""
    items = {}
    if section is None:
        return items
    for li in section.select('.comInfoList > ul.nmbGroup > li.number'):
        label_node = li.find('div', class_='txt', recursive=False)
        label = label_node.get_text(strip=True) if label_node else ''
        bullets = [
            _text(bullet.select_one('.txt'))
            for bullet in li.select('ul.bltGroup > li.bullet')
        ]
        items[label] = [b for b in bullets if b]
    return items


def _definition_and_basis(soup):
    section = _find_section(soup, '자격정의 및 관련근거')
    items = _numbered_items(section)
    definition = next((v[0] for k, v in items.items() if k.startswith('자격정의') and v), '')
    legal_basis = next((v for k, v in items.items() if k.startswith('관련근거')), [])
    return definition, ' / '.join(legal_basis)


def _written_subjects(soup):
    section = _find_section(soup, '필기시험과목')
    items = _numbered_items(section)
    subjects = []
    for bullets in items.values():
        subjects.extend(bullets)
    return ', '.join(subjects)


def _sport_events_summary(soup):
    section = _find_section(soup, '자격종목')
    items = _numbered_items(section)
    if not items:
        return ''
    return ' / '.join(f'{label}: {", ".join(bullets)}' for label, bullets in items.items() if bullets)


def _agencies(soup):
    section = _find_section(soup, '자격검정기관 및 연수기관 지정현황')
    exam_agency = training_agency = ''
    if section is None:
        return exam_agency, training_agency
    for tr in section.select('table tbody tr'):
        th, td = tr.find('th'), tr.find('td')
        if th is None or td is None:
            continue
        label = th.get_text(strip=True)
        value = td.get_text(strip=True)
        if '검정기관' in label:
            exam_agency = value
        elif '연수기관' in label:
            training_agency = value
    return exam_agency, training_agency


def _pass_criteria(soup):
    section = _find_section(soup, '유의사항')
    items = _numbered_items(section)
    for label, bullets in items.items():
        if '이수기준' in label or '합격' in label:
            return '; '.join(bullets)
    return ''


def _disqualification_text(soup):
    section = _find_section(soup, '체육지도자 결격')
    if section is None:
        return ''
    parts = []
    for desc in section.select('.cptAddsDesc .descArea'):
        heading = desc.find('p', class_='txt')
        if heading:
            parts.append(_text(heading))
        for item in desc.select('ul.descList > li.item'):
            parts.append(_text(item))
    return '\n'.join(p for p in parts if p)


def _eligibility_paths(soup, grade_code):
    section = _find_section(soup, '자격요건 및 제출서류')
    rows = []
    if section is None:
        return rows
    table = section.select_one('table.tableType')
    if table is None:
        return rows
    for tr in table.select('tbody tr'):
        cells = tr.find_all('td')
        if len(cells) < 4:
            continue
        course_type = _text(cells[0].select_one('.cont') or cells[0])
        eligibility = _text(cells[1].select_one('.cont') or cells[1])
        process = _text(cells[2].select_one('.cont') or cells[2])
        documents = _text(cells[3].select_one('.cont') or cells[3])
        rows.append({
            'grade_code': grade_code,
            'course_type': course_type,
            'eligibility': eligibility,
            'acquisition_process': process,
            'submitted_documents': documents,
        })
    return rows


def parse_license_html(html, grade_code):
    """licenseInfo{Grade}.kspo 응답 HTML -> (grade_summary dict, eligibility_paths list, 결격사유 text)."""
    soup = BeautifulSoup(html, 'html.parser')
    definition, legal_basis = _definition_and_basis(soup)
    exam_agency, training_agency = _agencies(soup)

    grade_summary = {
        'grade_code': grade_code,
        'grade_name': GRADE_NAMES.get(grade_code, grade_code),
        'definition': definition,
        'legal_basis': legal_basis,
        'written_subjects': _written_subjects(soup),
        'sport_events_summary': _sport_events_summary(soup),
        'exam_agency': exam_agency,
        'training_agency': training_agency,
        'pass_criteria': _pass_criteria(soup),
    }
    eligibility_paths = _eligibility_paths(soup, grade_code)
    disqualification_text = _disqualification_text(soup)
    return grade_summary, eligibility_paths, disqualification_text


def fetch_license_info(grade_code):
    """네트워크 요청 + 파싱을 함께 수행. 실패 시 KspoFetchError가 전파된다."""
    html = fetch(license_info_url(grade_code))
    return parse_license_html(html, grade_code)
