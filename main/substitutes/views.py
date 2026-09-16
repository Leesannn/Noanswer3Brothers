from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from analytics.services.normalizers import normalize_region

from . import selectors
from .forms import ApplyForm, EvaluationForm, ManagerVerifyForm, PostingForm
from .models import Application, CenterContact, PhoneIdentity, Posting, ReputationRecord
from .services import pass_auth
from .services.certification import has_required_certification
from .services.phone import hash_phone, mask_phone
from .services.tokens import generate_management_token, verify_management_token


MANAGER_SESSION_KEY = 'substitutes_manager_phone_hash'


def posting_list(request):
    postings = selectors.apply_posting_filters(request.GET)
    page_obj = Paginator(postings, 20).get_page(request.GET.get('page'))
    context = selectors.filter_options()
    context.update({'page_obj': page_obj, 'current': request.GET})
    return render(request, 'substitutes/list.html', context)


def posting_detail(request, pk):
    posting = get_object_or_404(Posting.objects.select_related('sport', 'manager'), pk=pk)
    return render(request, 'substitutes/detail.html', {'posting': posting})


def application_apply(request, pk):
    posting = get_object_or_404(Posting, pk=pk)
    if posting.status != Posting.Status.RECRUITING:
        messages.error(request, '이미 마감되었거나 완료된 공고입니다.')
        return redirect('substitutes:posting_detail', pk=posting.pk)

    if request.method == 'POST':
        form = ApplyForm(request.POST)
        if form.is_valid():
            identity = pass_auth.verify_pass_result(form.cleaned_data['name'], form.cleaned_data['phone'])
            if identity is None:
                form.add_error(None, 'PASS 본인인증에 실패했습니다. 다시 시도해주세요.')
            else:
                phone_hash = hash_phone(identity.phone)
                phone_masked = mask_phone(identity.phone)
                if not has_required_certification(phone_hash, posting.required_certifications):
                    messages.error(request, '이 공고에 필요한 자격증 보유자만 신청할 수 있습니다.')
                elif Application.objects.filter(posting=posting, phone_identity__phone_hash=phone_hash).exists():
                    messages.error(request, '이미 신청한 공고입니다.')
                else:
                    phone_identity, _ = PhoneIdentity.objects.get_or_create(
                        phone_hash=phone_hash, defaults={'phone_masked': phone_masked},
                    )
                    application = Application.objects.create(
                        posting=posting, phone_identity=phone_identity,
                        phone_masked=phone_masked, certification_verified=True,
                    )
                    return render(request, 'substitutes/apply_complete.html', {
                        'posting': posting, 'application': application,
                    })
    else:
        form = ApplyForm()
    return render(request, 'substitutes/apply.html', {'posting': posting, 'form': form})


def posting_create(request):
    manager_phone_hash = request.session.get(MANAGER_SESSION_KEY)
    manager = None
    if manager_phone_hash:
        manager = CenterContact.objects.filter(phone_hash=manager_phone_hash).first()

    if manager is None:
        if request.method == 'POST':
            verify_form = ManagerVerifyForm(request.POST)
            if verify_form.is_valid():
                identity = pass_auth.verify_pass_result(
                    verify_form.cleaned_data['institution_name'], verify_form.cleaned_data['phone'],
                )
                if identity is None:
                    verify_form.add_error(None, '휴대폰 인증에 실패했습니다. 다시 시도해주세요.')
                else:
                    phone_hash = hash_phone(identity.phone)
                    manager, _ = CenterContact.objects.update_or_create(
                        phone_hash=phone_hash,
                        defaults={
                            'phone_masked': mask_phone(identity.phone),
                            'institution_name': verify_form.cleaned_data['institution_name'],
                            'business_reg_no': verify_form.cleaned_data['business_reg_no'],
                            'verified_at': timezone.now(),
                        },
                    )
                    request.session[MANAGER_SESSION_KEY] = phone_hash
                    return redirect('substitutes:posting_create')
        else:
            verify_form = ManagerVerifyForm()
        return render(request, 'substitutes/create_verify.html', {'form': verify_form})

    if request.method == 'POST':
        posting_form = PostingForm(request.POST)
        if posting_form.is_valid():
            posting = posting_form.save(commit=False)
            posting.manager = manager
            posting.normalized_region = normalize_region(posting.region)
            posting.save()
            management_url = request.build_absolute_uri(
                reverse('substitutes:applicant_manage', args=[posting.pk, generate_management_token(posting.pk)]),
            )
            messages.success(
                request,
                f'공고가 등록되었습니다. 아래 관리 링크로 신청자 확인·평가를 할 수 있으니 보관해주세요.\n{management_url}',
            )
            return redirect('substitutes:posting_detail', pk=posting.pk)
    else:
        posting_form = PostingForm()
    return render(request, 'substitutes/create.html', {'form': posting_form, 'manager': manager})


def _get_posting_for_token(pk, token):
    posting_id = verify_management_token(token)
    if posting_id != pk:
        raise Http404('관리 링크가 올바르지 않습니다.')
    return get_object_or_404(Posting.objects.select_related('sport', 'manager'), pk=pk)


def applicant_manage(request, pk, token):
    posting = _get_posting_for_token(pk, token)
    applications = posting.applications.select_related('phone_identity').order_by('-applied_at')
    rows = [
        {'application': application, 'summary': selectors.get_reputation_summary(application.phone_identity)}
        for application in applications
    ]
    return render(request, 'substitutes/manage.html', {
        'posting': posting, 'rows': rows, 'token': token, 'eval_form': EvaluationForm(),
    })


def application_evaluate(request, pk, token, application_id):
    posting = _get_posting_for_token(pk, token)
    application = get_object_or_404(Application, pk=application_id, posting=posting)

    if request.method == 'POST':
        form = EvaluationForm(request.POST)
        if form.is_valid():
            ReputationRecord.objects.create(
                phone_identity=application.phone_identity,
                posting=posting,
                is_no_show=form.cleaned_data['no_show'],
                is_complaint=form.cleaned_data['complaint'],
                positive_tags=form.cleaned_data['positive_tags'],
                comment=form.cleaned_data['comment'],
                created_by=posting.manager,
            )
            messages.success(request, '평가를 등록했습니다.')
        else:
            messages.error(request, '평가 내용을 확인해주세요. 하나 이상 선택해야 합니다.')
    return redirect('substitutes:applicant_manage', pk=posting.pk, token=token)
