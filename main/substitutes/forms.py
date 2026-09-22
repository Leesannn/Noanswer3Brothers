from django import forms

from analytics.models import CanonicalSport

from .models import POSITIVE_TAG_CHOICES, Posting


CERTIFICATION_CHOICES = [
    ('생활스포츠지도사 2급', '생활스포츠지도사 2급'),
    ('생활스포츠지도사 1급', '생활스포츠지도사 1급'),
    ('유소년스포츠지도사', '유소년스포츠지도사'),
    ('노인스포츠지도사', '노인스포츠지도사'),
    ('장애인스포츠지도사', '장애인스포츠지도사'),
    ('인명구조자격', '인명구조자격'),
]


def _apply_widget_classes(fields):
    for field in fields.values():
        widget = field.widget
        if isinstance(widget, (forms.CheckboxSelectMultiple, forms.RadioSelect, forms.CheckboxInput)):
            continue
        css_class = 'form-select' if isinstance(widget, forms.Select) else 'form-control'
        widget.attrs['class'] = f"{widget.attrs.get('class', '')} {css_class}".strip()


class ManagerVerifyForm(forms.Form):
    institution_name = forms.CharField(label='기관명', max_length=200)
    business_reg_no = forms.CharField(label='사업자등록번호', max_length=20, required=False, help_text='선택 입력입니다.')
    phone = forms.CharField(label='담당자 휴대폰 번호', max_length=20)
    password = forms.CharField(
        label='비밀번호', widget=forms.PasswordInput, min_length=4, max_length=20,
        help_text='같은 번호로 다시 공고를 등록할 때 필요하니 잊지 마세요.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_widget_classes(self.fields)


class PostingForm(forms.ModelForm):
    required_certifications = forms.MultipleChoiceField(
        label='필요 자격증', choices=CERTIFICATION_CHOICES, widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Posting
        fields = [
            'sport', 'work_date', 'start_time', 'end_time', 'region', 'address',
            'required_certifications', 'pay_amount', 'pay_unit', 'headcount', 'description',
        ]
        labels = {
            'sport': '종목', 'work_date': '날짜', 'start_time': '시작 시간', 'end_time': '종료 시간',
            'region': '지역', 'address': '장소(주소)', 'pay_amount': '시급/페이', 'pay_unit': '단위',
            'headcount': '모집 인원', 'description': '상세 요청사항',
        }
        widgets = {
            'work_date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
            'description': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sport'].queryset = CanonicalSport.objects.filter(is_active=True).order_by('name')
        _apply_widget_classes(self.fields)

    def clean_region(self):
        return self.cleaned_data['region'].strip()


class ApplyForm(forms.Form):
    name = forms.CharField(label='이름', max_length=50)
    phone = forms.CharField(label='휴대폰 번호', max_length=20)
    password = forms.CharField(
        label='비밀번호', widget=forms.PasswordInput, min_length=4, max_length=20,
        help_text='같은 번호로 다시 신청할 때 본인 확인에 사용됩니다.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_widget_classes(self.fields)


class EvaluationForm(forms.Form):
    no_show = forms.BooleanField(label='노쇼 발생', required=False)
    complaint = forms.BooleanField(label='컴플레인 발생', required=False)
    positive_tags = forms.MultipleChoiceField(
        label='긍정 태그', choices=[(tag, tag) for tag in POSITIVE_TAG_CHOICES],
        required=False, widget=forms.CheckboxSelectMultiple,
    )
    comment = forms.CharField(label='코멘트', required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_widget_classes(self.fields)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('no_show') and not cleaned.get('complaint') and not cleaned.get('positive_tags'):
            raise forms.ValidationError('노쇼, 컴플레인, 긍정 태그 중 하나 이상을 선택해주세요.')
        return cleaned
