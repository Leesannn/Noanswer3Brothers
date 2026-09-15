import hashlib
import hmac

from django.conf import settings


def normalize_phone(raw_phone):
    digits = ''.join(ch for ch in raw_phone if ch.isdigit())
    if digits.startswith('82') and not digits.startswith('820'):
        digits = '0' + digits[2:]
    return digits


def hash_phone(raw_phone):
    """전화번호 원문을 서버 SECRET_KEY로 HMAC-SHA256 해시한다.

    해시값만 영구 저장하고 원문은 호출 직후 폐기한다.
    """
    digits = normalize_phone(raw_phone)
    return hmac.new(settings.SECRET_KEY.encode('utf-8'), digits.encode('utf-8'), hashlib.sha256).hexdigest()


def mask_phone(raw_phone):
    digits = normalize_phone(raw_phone)
    if len(digits) < 7:
        return digits
    return f'{digits[:3]}-****-{digits[-4:]}'
