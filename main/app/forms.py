from django import forms

from .models import CanonicalSport, Institution, ProgramCleanup, QualificationAggregate, UploadBatch
from .services.importers import FIELD_LABELS


class UploadForm(forms.Form):
    dataset_type = forms.ChoiceField(label='데이터 종류', choices=UploadBatch.DatasetType.choices)
    file = forms.FileField(label='CSV 또는 XLSX 파일')
    sheet_name = forms.CharField(label='XLSX 시트명', required=False, help_text='비워 두면 첫 번째 시트를 사용합니다.')

    def clean_file(self):
        file = self.cleaned_data['file']
        if not file.name.lower().endswith(('.csv', '.xlsx')):
            raise forms.ValidationError('CSV 또는 XLSX 파일만 업로드할 수 있습니다.')
        return file


class MappingForm(forms.Form):
    def __init__(self, *args, dataset_type, columns, suggested=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [('', '선택 안 함')] + [(column, column) for column in columns]
        suggested = suggested or {}
        for field, label in FIELD_LABELS[dataset_type].items():
            self.fields[field] = forms.ChoiceField(
                label=label, choices=choices, required=False, initial=suggested.get(field, ''),
            )
        self.fields['allow_invalid'] = forms.BooleanField(
            label='오류 행을 제외하고 유효한 행만 저장', required=False,
            help_text='선택하지 않으면 오류가 하나라도 있을 때 전체 저장을 취소합니다.',
        )


TARGET_CHOICES = [
    ('', '대상을 선택하지 않음'),
    ('유아·아동', '유아·아동'),
    ('청소년', '청소년'),
    ('성인', '성인'),
    ('어르신', '어르신'),
    ('장애인', '장애인'),
]
TIME_CHOICES = [
    ('', '시간대를 선택하지 않음'),
    ('morning', '오전 (12시 이전)'),
    ('afternoon', '오후 (12~18시)'),
    ('evening', '저녁 (18시 이후)'),
]
WEEKDAY_CHOICES = [(day, day) for day in '월화수목금토일']


def _sport_queryset():
    return CanonicalSport.objects.filter(
        is_active=True,
        cleaned_programs__operating_status=ProgramCleanup.OperatingStatus.ACTIVE,
        cleaned_programs__is_usable=True,
    ).distinct().order_by('name')


def _region_choices():
    labels = {}
    rows = Institution.objects.exclude(normalized_region='').values_list(
        'normalized_region', 'region',
    ).order_by('normalized_region', 'region')
    for key, label in rows:
        labels.setdefault(key, label or key)
    return [('', '지역을 선택하세요')] + [
        (key, f'{label} ({key})' if label != key else key)
        for key, label in labels.items()
    ]


class RecommendationFormMixin:
    def _apply_widget_classes(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                continue
            css_class = 'form-select' if isinstance(widget, forms.Select) else 'form-control'
            widget.attrs['class'] = f"{widget.attrs.get('class', '')} {css_class}".strip()


class LicensedRecommendationForm(RecommendationFormMixin, forms.Form):
    qualification_type = forms.ChoiceField(label='보유 자격 또는 자격 종류')
    sport = forms.ModelChoiceField(label='지도 종목', queryset=CanonicalSport.objects.none())
    region = forms.ChoiceField(label='활동 희망 지역')
    district = forms.CharField(
        label='세부 지역', required=False, max_length=30,
        help_text='시·군·구까지만 입력해 주세요. 예: 성동구, 수원시',
    )
    mobility = forms.ChoiceField(label='이동 가능 범위', choices=[
        ('district', '같은 시·군·구'),
        ('province', '같은 시·도'),
        ('any', '지역 무관'),
    ], initial='province')
    target = forms.ChoiceField(label='희망 지도 대상', choices=TARGET_CHOICES, required=False)
    weekdays = forms.MultipleChoiceField(
        label='활동 가능한 요일', choices=WEEKDAY_CHOICES, required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    time_band = forms.ChoiceField(label='선호 시간대', choices=TIME_CHOICES, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        types = QualificationAggregate.objects.exclude(
            qualification_type='',
        ).values_list('qualification_type', flat=True).distinct().order_by('qualification_type')
        self.fields['qualification_type'].choices = [('', '자격 종류를 선택하세요')] + [
            (value, value) for value in types
        ]
        self.fields['sport'].queryset = _sport_queryset()
        self.fields['sport'].empty_label = '종목을 선택하세요'
        self.fields['region'].choices = _region_choices()
        self._apply_widget_classes()


class UnlicensedRecommendationForm(RecommendationFormMixin, forms.Form):
    region = forms.ChoiceField(label='거주 또는 활동 희망 지역')
    primary_sport = forms.ModelChoiceField(
        label='주요 관심 종목 또는 취미', queryset=CanonicalSport.objects.none(),
    )
    additional_sports = forms.ModelMultipleChoiceField(
        label='추가 관심 종목', queryset=CanonicalSport.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='최대 2개까지 선택할 수 있습니다.',
    )
    experience = forms.ChoiceField(label='운동 경험 수준', choices=[
        ('beginner', '처음 시작'),
        ('hobby', '취미 경험 있음'),
        ('expert', '대회 또는 전문 경험 있음'),
    ], required=False)
    target = forms.ChoiceField(label='지도하고 싶은 대상', choices=TARGET_CHOICES, required=False)
    time_band = forms.ChoiceField(label='활동 가능한 시간대', choices=TIME_CHOICES, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sports = _sport_queryset()
        self.fields['primary_sport'].queryset = sports
        self.fields['primary_sport'].empty_label = '종목을 선택하세요'
        self.fields['additional_sports'].queryset = sports
        self.fields['region'].choices = _region_choices()
        self._apply_widget_classes()

    def clean(self):
        cleaned = super().clean()
        additional = cleaned.get('additional_sports')
        primary = cleaned.get('primary_sport')
        if additional is not None and additional.count() > 2:
            self.add_error('additional_sports', '추가 관심 종목은 최대 2개까지 선택할 수 있습니다.')
        if primary and additional is not None and additional.filter(pk=primary.pk).exists():
            self.add_error('additional_sports', '주요 관심 종목과 다른 종목을 선택해 주세요.')
        return cleaned
