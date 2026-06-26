from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_journal_break_even_value'),
    ]

    operations = [
        migrations.CreateModel(
            name='ImportBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(choices=[('mt5_html', 'MT5 HTML Report')], max_length=50)),
                ('filename', models.CharField(blank=True, max_length=255)),
                ('imported_at', models.DateTimeField(auto_now_add=True)),
                ('rows_parsed', models.IntegerField(default=0)),
                ('trades_created', models.IntegerField(default=0)),
                ('trades_skipped', models.IntegerField(default=0)),
                ('trades_failed', models.IntegerField(default=0)),
                ('journal', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='import_batches', to='core.journal')),
            ],
            options={
                'ordering': ['-imported_at'],
            },
        ),
        migrations.CreateModel(
            name='TradeImport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(max_length=50)),
                ('external_id', models.CharField(max_length=100)),
                ('raw_profit', models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('raw_data', models.JSONField(default=dict)),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='imported_trades', to='core.importbatch')),
                ('journal', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='trade_imports', to='core.journal')),
                ('trade', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='import_record', to='core.trade')),
            ],
            options={
                'unique_together': {('journal', 'source', 'external_id')},
            },
        ),
    ]
