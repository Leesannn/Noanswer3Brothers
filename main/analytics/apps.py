from django.apps import AppConfig


class SportsAnalyticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    # 패키지는 analytics로 옮겼지만, 기존 마이그레이션·DB 테이블·ContentType이
    # 전부 app_label='app' 기준으로 이미 만들어져 있어 label은 그대로 둔다.
    # (label을 바꾸면 마이그레이션을 다시 만들고 기존 DB를 이관해야 한다.)
    name = 'analytics'
    label = 'app'
    verbose_name = '스포츠 데이터 분석'
