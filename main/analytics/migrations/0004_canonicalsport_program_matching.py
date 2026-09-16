from django.db import migrations, models
import django.db.models.deletion


def populate_taxonomy(apps, schema_editor):
    QualificationAggregate = apps.get_model('app', 'QualificationAggregate')
    CanonicalSport = apps.get_model('app', 'CanonicalSport')
    from django.db.models import Sum
    rows = QualificationAggregate.objects.exclude(normalized_sport='').values(
        'normalized_sport', 'sport',
    ).annotate(total=Sum('acquisition_count')).order_by('normalized_sport', '-total', 'sport')
    selected = {}
    totals = {}
    for row in rows:
        key = row['normalized_sport']
        totals[key] = totals.get(key, 0) + (row['total'] or 0)
        selected.setdefault(key, row['sport'])
    CanonicalSport.objects.bulk_create([
        CanonicalSport(name=selected[key], normalized_name=key, qualification_count=totals[key])
        for key in sorted(selected)
    ])


class Migration(migrations.Migration):
    dependencies = [('app', '0003_alter_applicationstatus_is_synthetic_and_more')]

    operations = [
        migrations.CreateModel(
            name='CanonicalSport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150)),
                ('normalized_name', models.CharField(max_length=150, unique=True)),
                ('qualification_count', models.PositiveBigIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={'verbose_name': '기준 종목', 'verbose_name_plural': '기준 종목', 'ordering': ['name']},
        ),
        migrations.AddField(model_name='program', name='program_type', field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name='program', name='facility_industry', field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name='program', name='matched_sport', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='matched_programs', to='app.canonicalsport')),
        migrations.AddField(model_name='program', name='match_grade', field=models.CharField(choices=[('exact', '정확'), ('similar', '유사'), ('review', '검토 필요'), ('unmatched', '미매칭')], db_index=True, default='unmatched', max_length=20)),
        migrations.AddField(model_name='program', name='match_confidence', field=models.PositiveSmallIntegerField(default=0)),
        migrations.AddField(model_name='program', name='match_reason', field=models.TextField(blank=True)),
        migrations.AddField(model_name='program', name='match_rules', field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name='program', name='match_candidates', field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name='program', name='match_is_manual', field=models.BooleanField(db_index=True, default=False)),
        migrations.AddField(model_name='program', name='match_updated_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.RunPython(populate_taxonomy, migrations.RunPython.noop),
    ]
