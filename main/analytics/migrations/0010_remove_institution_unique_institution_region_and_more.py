from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0009_alter_applicationstatus_program_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='institution',
            name='unique_institution_region',
        ),
        migrations.AddField(
            model_name='institution',
            name='normalized_address',
            field=models.CharField(blank=True, default='', max_length=500),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='programcleanup',
            name='exclusion_reason',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', '사용'), ('ended', '운영 종료'), ('upcoming', '운영 예정'),
                    ('unknown', '운영 여부 미확인'), ('multi_sport', '복수 종목'),
                    ('unmatched', '자격 종목 미매칭'), ('other', '기타 제외'),
                ],
                db_index=True,
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name='programcleanup',
            name='operating_status',
            field=models.CharField(
                choices=[
                    ('active', '운영 중'), ('ended', '운영 종료'),
                    ('upcoming', '운영 예정'), ('unknown', '미확인'),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name='institution',
            constraint=models.UniqueConstraint(
                fields=('normalized_name', 'normalized_region', 'normalized_address'),
                name='unique_institution_region_address',
            ),
        ),
    ]
