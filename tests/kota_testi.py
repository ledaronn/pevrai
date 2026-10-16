"""Limited provider calls require a valid, durable, atomic quota reservation."""
from contextlib import ExitStack
from datetime import datetime, timedelta
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pevrai import journal, vekil_v0 as v
from pevrai.model.taban import OranSiniri, SunucuHatasi, ZamanAsimi


def _last_request_worker(root, barrier, results):
    root = Path(root)
    provider = SimpleNamespace(uret=Mock(return_value=object()))
    fake = SimpleNamespace(politika=SimpleNamespace(gunluk_tavan={'varsayilan': 1}), semalar=[])
    try:
        with patch.object(journal, 'KOK', root), patch.object(journal, 'KOTA', root/'kota.json'), \
             patch.object(v, 'B', fake), patch.object(v, 'sistem_talimati', return_value=''):
            barrier.wait(timeout=20)
            try:
                v._model_cagir(provider, [], 'fake', 'varsayilan')
                status = 'sent'
            except v.TavanDoldu:
                status = 'full'
        results.put((status, provider.uret.call_count))
    except Exception as exc:
        results.put((type(exc).__name__, provider.uret.call_count))


class Quota(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.quota = self.root/'kota.json'
        self.today = datetime.now().strftime('%Y-%m-%d')
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(journal, 'KOK', self.root))
        self.stack.enter_context(patch.object(journal, 'KOTA', self.quota))
        self.provider = SimpleNamespace(uret=Mock(return_value=object()))
        self.policy = SimpleNamespace(gunluk_tavan={'varsayilan': 3, 'guclu': 2})
        self.stack.enter_context(patch.object(v, 'B', SimpleNamespace(politika=self.policy, semalar=[])))
        self.stack.enter_context(patch.object(v, 'sistem_talimati', return_value=''))
        self.stack.enter_context(patch.object(v, '_yeniden_deneme_bekle'))

    def write(self, counts=None, date=None):
        self.quota.write_text(json.dumps({'tarih': date or self.today,
                                         'sayaclar': counts or {}}), encoding='utf-8')

    def call(self, **kwargs):
        return v._model_cagir(self.provider, [], 'fake', 'varsayilan', **kwargs)

    def test_fresh_counts_and_role_limits(self):
        self.assertEqual(journal.kota_sayaclari(), {})
        for _ in range(3):
            self.call()
        with self.assertRaises(v.TavanDoldu) as error:
            self.call()
        self.assertEqual((error.exception.sayi, error.exception.tavan), (3, 3))
        self.assertIsNone(journal.kota_ayir('guclu', self.policy.gunluk_tavan))
        self.assertEqual(journal.kota_sayaclari(), {'varsayilan': 3, 'guclu': 1})
        self.assertEqual(self.provider.uret.call_count, 3)

    def test_valid_old_day_resets_both_roles(self):
        self.write({'varsayilan': 99, 'guclu': 99},
                   (datetime.now()-timedelta(days=1)).strftime('%Y-%m-%d'))
        self.call()
        self.assertEqual(journal.kota_sayaclari(), {'varsayilan': 1})

    def test_bad_json_schema_and_values_never_send_or_overwrite(self):
        bad = ['{broken', '[]', '{}']
        bad += [json.dumps({'tarih': self.today, 'sayaclar': c}) for c in
                [[], None, {'varsayilan': True}, {'varsayilan': -1},
                 {'varsayilan': 1.5}, {'varsayilan': '1'}, {'unknown': 1}]]
        bad += [json.dumps({'tarih': d, 'sayaclar': {}}) for d in
                [None, 4, '2026-1-1', 'not-a-date', '9999-12-31']]
        bad += ['{"tarih":"'+self.today+'","sayaclar":{"varsayilan":3,"varsayilan":0}}']
        for text in bad:
            with self.subTest(text=text):
                self.quota.write_text(text, encoding='utf-8')
                with self.assertRaises(journal.KotaHatasi):
                    self.call()
                with self.assertRaises(journal.KotaHatasi):
                    journal.kota_sayaclari()
                self.assertEqual(self.quota.read_text('utf-8'), text)
        self.provider.uret.assert_not_called()

    def test_corruption_in_old_day_is_not_a_new_budget(self):
        self.write({'varsayilan': -1}, '2000-01-01')
        with self.assertRaises(journal.KotaHatasi):
            self.call()
        self.provider.uret.assert_not_called()

    def test_read_failure_does_not_send_or_leak_paths(self):
        with patch.object(Path, 'read_text', side_effect=PermissionError('private-path secret')):
            with self.assertRaises(journal.KotaHatasi) as error:
                self.call()
        self.assertNotIn('private-path', str(error.exception))
        self.assertNotIn('secret', str(error.exception))
        self.provider.uret.assert_not_called()

    def test_directory_counter_is_not_missing(self):
        self.quota.mkdir()
        with self.assertRaises(journal.KotaHatasi):
            self.call()
        self.provider.uret.assert_not_called()

    def test_write_failure_keeps_previous_count_and_task_budget(self):
        self.write({'varsayilan': 1})
        previous = self.quota.read_bytes()
        budget = {'istek': 0, 'toplam': 4}
        with patch.object(journal.os, 'replace', side_effect=PermissionError('secret-path')):
            with self.assertRaises(journal.KotaHatasi):
                self.call(istek_sayaci=budget)
        self.assertEqual(self.quota.read_bytes(), previous)
        self.assertEqual(list(self.root.glob('.kota-*.tmp')), [])
        self.assertEqual(budget, {'istek': 0, 'toplam': 4})
        self.provider.uret.assert_not_called()

    def test_flush_failure_prevents_replace_and_request(self):
        self.write({'varsayilan': 1})
        with patch.object(journal.os, 'fsync', side_effect=OSError('disk')), \
             patch.object(journal.os, 'replace') as replace:
            with self.assertRaises(journal.KotaHatasi):
                self.call()
        replace.assert_not_called()
        self.assertEqual(journal.kota_sayaclari(), {'varsayilan': 1})
        self.provider.uret.assert_not_called()

    def test_lock_acquisition_failure_prevents_write_and_request(self):
        if os.name == 'nt':
            import msvcrt
            target, method = msvcrt, 'locking'
        else:
            import fcntl
            target, method = fcntl, 'flock'
        with patch.object(target, method, side_effect=OSError('lock')), \
             patch.object(journal, '_kota_yaz') as write:
            with self.assertRaises(journal.KotaHatasi):
                self.call()
        write.assert_not_called()
        self.provider.uret.assert_not_called()

    def test_atomic_replacement_readers_see_complete_snapshot(self):
        self.write({'varsayilan': 1})
        replace = os.replace
        def observe(src, dst):
            self.assertEqual(journal.kota_sayaclari(), {'varsayilan': 1})
            self.assertEqual(Path(src).parent, self.quota.parent)
            self.assertEqual(json.loads(Path(src).read_text('utf-8'))['sayaclar'], {'varsayilan': 2})
            replace(src, dst)
        with patch.object(journal.os, 'replace', side_effect=observe):
            self.call()
        self.assertEqual(journal.kota_sayaclari(), {'varsayilan': 2})

    def test_disabled_limit_allows_calls_without_resetting_bad_counter(self):
        self.policy.gunluk_tavan['varsayilan'] = 0
        self.quota.write_text('{broken', encoding='utf-8')
        self.call()
        self.provider.uret.assert_called_once()
        self.assertEqual(self.quota.read_text('utf-8'), '{broken')

    def test_invalid_role_or_limit_cannot_disable_protection(self):
        for role, limit in [('typo', 1), ('varsayilan', -1), ('varsayilan', True), ('varsayilan', '1')]:
            with self.subTest(role=role, limit=limit), self.assertRaises(journal.KotaHatasi):
                journal.kota_ayir(role, {role: limit})
        self.assertFalse(self.quota.exists())

    def test_retry_attempts_and_forced_tool_count_as_requests(self):
        for error in [OranSiniri(429, 'rate'), SunucuHatasi(503, 'busy'), ZamanAsimi('timeout')]:
            with self.subTest(error=type(error).__name__):
                self.write()
                self.provider.uret.reset_mock()
                self.provider.uret.side_effect = [error, error, object()]
                budget = {}
                self.call(istek_sayaci=budget, zorla_arac='durum_yaz', arac_listesi=[])
                self.assertEqual(self.provider.uret.call_count, 3)
                self.assertEqual(journal.kota_sayaclari()['varsayilan'], 3)
                self.assertEqual(budget, {'istek': 3, 'toplam': 3})
                self.assertEqual(self.provider.uret.call_args.args[-1], 'durum_yaz')

    def test_retry_cannot_cross_last_daily_request(self):
        self.policy.gunluk_tavan['varsayilan'] = 1
        self.provider.uret.side_effect = SunucuHatasi(503, 'busy')
        with self.assertRaises(v.TavanDoldu):
            self.call()
        self.provider.uret.assert_called_once()

    def test_ui_reports_unknown_usage_instead_of_zero(self):
        from pevrai.pencere import Api
        self.quota.write_text('{broken', encoding='utf-8')
        api = Api.__new__(Api)
        api._politika = SimpleNamespace(
            gunluk_tavan={'varsayilan': 3}, mod_coz=lambda _: {'model': 'varsayilan'})
        for response in (api.kota(), api.mod_kotasi('hizli')):
            self.assertFalse(response['ok'])
            self.assertIn('hata', response)
            self.assertNotIn('kalan', response)
            self.assertNotIn('satirlar', response)

    def test_task_publishes_safe_error_without_switching_provider(self):
        from pevrai.olaylar import OlayTipi, Oturum
        events = []
        session = Oturum(onay_saglayici=lambda _: False, yayinla=events.append)
        self.quota.write_text('{broken', encoding='utf-8')
        fake = SimpleNamespace(politika=self.policy, semalar=[], ajan=None, ajan_adi='', ekip_pano=None)
        link = SimpleNamespace(model='fake', etiket='fake')
        log = {}
        with patch.object(v, 'B', fake), \
             patch.object(v, '_mod_coz_gorev', return_value=({'model': 'varsayilan', 'adim': 2, 'cagri': 2, 'istek': 2}, 'hizli')), \
             patch.object(v.model_zinciri, 'zincir', return_value=[link]), \
             patch.object(v.model_zinciri, 'sirala', side_effect=lambda links: links), \
             patch.object(v, '_halka_kur', return_value=(0, self.provider)) as setup, \
             patch.object(v, 'mcp_baglan'), patch.object(v, '_gorev_araclari', return_value=None):
            text, resume_id = v._calistir_ic('synthetic task', None, session, None, kayit=log)
        self.assertIsNone(resume_id)
        self.assertEqual(setup.call_count, 1)
        self.provider.uret.assert_not_called()
        errors = [event for event in events if event.tip == OlayTipi.HATA]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].veri['mesaj'], text)
        self.assertNotIn(str(self.root), text)
        self.assertEqual(len(log['engeller']), 1)

    def test_task_summary_keeps_unknown_usage_and_preserves_result(self):
        from pevrai.durum import ozet_metni
        self.quota.write_text('{broken', encoding='utf-8')
        log = {}
        with patch.object(journal, 'gorev_kayitlari', return_value=[]), \
             patch.object(v, '_ozet_yaz', return_value=(None, 'synthetic offline')):
            result = v._ozet_bitir('completed', log, None, 0, {'toplam': 2}, 'varsayilan',
                                   datetime.now(), '', '', None)
        self.assertIn('completed', result)
        self.assertEqual(log['kota'], {})
        self.assertTrue(log['kota_hatasi'])
        self.assertIn(log['kota_hatasi'], ozet_metni(log))

    def test_last_request_is_reserved_once_across_processes(self):
        context = multiprocessing.get_context('spawn')
        barrier = context.Barrier(3)
        results = context.Queue()
        children = [context.Process(target=_last_request_worker,
                                    args=(str(self.root), barrier, results)) for _ in range(2)]
        try:
            for child in children:
                child.start()
            barrier.wait(timeout=30)
            observed = [results.get(timeout=30) for _ in children]
            for child in children:
                child.join(timeout=10)
                self.assertEqual(child.exitcode, 0)
            self.assertCountEqual(observed, [('sent', 1), ('full', 0)])
            self.assertEqual(journal.kota_sayaclari(), {'varsayilan': 1})
        finally:
            for child in children:
                if child.pid and child.is_alive():
                    child.terminate()
                    child.join(timeout=10)
            results.close()
            results.join_thread()


if __name__ == '__main__':
    unittest.main()
