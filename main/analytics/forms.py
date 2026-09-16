from django import forms

from .models import UploadBatch
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
