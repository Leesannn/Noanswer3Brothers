from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('app', '0004_canonicalsport_program_matching')]

    operations = [
        migrations.CreateModel(
            name='ProgramCleanup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cleaned_name', models.CharField(blank=True, max_length=400)),
                ('operating_status', models.CharField(choices=[('active', '운영 중'), ('ended', '운영 종료'), ('unknown', '미확인')], db_index=True, max_length=20)),
                ('is_usable', models.BooleanField(db_index=True, default=False)),
                ('exclusion_reason', models.CharField(blank=True, choices=[('', '사용'), ('ended', '운영 종료'), ('unknown', '운영 여부 미확인'), ('multi_sport', '복수 종목'), ('unmatched', '자격 종목 미매칭'), ('other', '기타 제외')], db_index=True, max_length=30)),
                ('evidence', models.TextField(blank=True)),
                ('rules', models.JSONField(blank=True, default=list)),
                ('reference_date', models.DateField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('matched_sport', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='cleaned_programs', to='app.canonicalsport')),
                ('program', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='cleanup', to='app.program')),
            ],
            options={
                'verbose_name': '프로그램 정리 결과',
                'verbose_name_plural': '프로그램 정리 결과',
                'ordering': ['program__institution__name', 'cleaned_name'],
            },
        ),
        migrations.AddIndex(model_name='programcleanup', index=models.Index(fields=['reference_date', 'operating_status', 'is_usable'], name='app_cleanup_usage_idx')),
        migrations.AddIndex(model_name='programcleanup', index=models.Index(fields=['matched_sport', 'is_usable'], name='app_cleanup_sport_idx')),
    ]
