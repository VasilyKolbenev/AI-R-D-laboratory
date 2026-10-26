"""Publication body is clean and media retains readable source resolution."""
from copy import deepcopy
import hashlib,io,json,math
from pathlib import Path
import subprocess,tempfile,unittest
from unittest.mock import patch
from laboratory import media_encoder
from laboratory.presentation import build_presentation,publication_rules,utf16_len
from laboratory.reader_infographic import render_infographic_gif
try:
    from . import test_presentation_auto_v08 as fixtures
except ImportError:
    import test_presentation_auto_v08 as fixtures

class PublishV09Tests(unittest.TestCase):
    def data(self):
        fixture=fixtures.AutomaticPresentationTests()
        return build_presentation(fixture.run_record())

    def test_ready_post_has_required_content_without_operational_scaffolding(self):
        data=self.data();text=data['post_text']
        self.assertEqual(data['publication_checks']['status'],'ready')
        for key in ['ПРОБЛЕМА','КОМУ ПОЛЕЗНО','КАК РАБОТАЕТ','ЧТО ПОКАЗАЛИ АВТОРЫ','ГРАНИЦЫ','НАСТРОЙКА И РЕСУРСЫ','ПРАКТИЧЕСКИЙ ВЫВОД','С ЧЕГО НАЧАТЬ','Источники']:
            self.assertIn(key,text)
        for noise in ['По сохранённому отчёту','Результаты из сохранённого отчёта','ЧЕРНОВИК','ИССЛЕДОВАНИЕ ЗАВЕРШЕНО','/result']:
            self.assertNotIn(noise,text)
        self.assertIn('Авторское сравнение',text)
        self.assertLessEqual(utf16_len(text),3500)
        self.assertEqual(data['publication_rules'],publication_rules())

    def test_compacted_post_is_not_mislabeled_publication_ready(self):
        fixture=fixtures.AutomaticPresentationTests();block=fixture.block()
        block['findings']=[('Длинное авторское утверждение. '*20)[:390]]*3
        block['limitations']=[('Длинное ограничение применимости. '*20)[:390]]*3
        block['resources']=[('Длинное описание инфраструктуры. '*20)[:390]]*3
        data=build_presentation(fixture.run_record(block))
        self.assertTrue(data['post_compacted'])
        self.assertEqual(data['publication_checks']['status'],'incomplete')
        self.assertTrue(any('не помещается' in issue for issue in data['publication_checks']['issues']))

    def test_missing_or_tampered_encoder_never_executes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'ffmpeg.exe').write_bytes(b'TEST_ONLY invalid binary')
            (root/'encoder.json').write_text(json.dumps({'sha256':'0'*64}),encoding='utf-8')
            with patch.object(media_encoder,'TOOLS',root),patch.object(subprocess,'Popen') as popen:
                self.assertIsNone(media_encoder.render_mp4(self.data()));popen.assert_not_called()

    def test_native_gif_fallback_and_metric_frame_do_not_downsample_text(self):
        from PIL import Image
        data=self.data();original=deepcopy(data)
        frame=media_encoder._comparison_frame(data,data['comparisons'][0],1)
        self.assertEqual(frame.width,1080);self.assertEqual(frame.height%2,0)
        with Image.open(io.BytesIO(render_infographic_gif(data))) as gif:self.assertEqual(gif.width,1080)
        self.assertEqual(data,original)

    def test_h264_roundtrip_keeps_native_text_quality(self):
        binary=media_encoder.encoder_path()
        if binary is None:self.skipTest('Optional local H.264 encoder missing')
        from PIL import Image,ImageChops,ImageStat
        # Verify both the new moving dashboard and the retained numeric path.
        for legacy in (False,True):
            with self.subTest(renderer='legacy_numeric' if legacy else 'motion_dashboard'):
                data=self.data()
                if legacy:data.pop('motion_story',None)
                content=media_encoder.render_mp4(data)
                self.assertIsNotNone(content);self.assertLess(len(content),8*1024*1024)
                self.assertIn(b'ftyp',content[:32]);self.assertIn(b'avc1',content)
                if data.get('motion_story'):
                    from laboratory.motion_dashboard import frame
                    last_index=math.ceil((media_encoder.MOTION_SECONDS-.1)*media_encoder.FPS)
                    expected=frame(data,last_index/(media_encoder.MOTION_SECONDS*media_encoder.FPS))
                else:expected=media_encoder._comparison_frame(data,data['comparisons'][0],1)
                with tempfile.TemporaryDirectory() as temp:
                    video=Path(temp)/'out.mp4';image=Path(temp)/'last.png';video.write_bytes(content)
                    result=subprocess.run([str(binary),'-hide_banner','-loglevel','error','-y','-sseof','-0.1','-i',str(video),'-frames:v','1',str(image)],capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    self.assertEqual(result.returncode,0)
                    with Image.open(image) as decoded:
                        self.assertEqual(decoded.size,expected.size);self.assertEqual(decoded.width,1080)
                        diff=ImageChops.difference(expected.convert('RGB'),decoded.convert('RGB'))
                        mse=sum(ImageStat.Stat(diff).sum2)/(expected.width*expected.height*3)
                        psnr=10*math.log10(255**2/max(mse,1e-9))
                        self.assertGreater(psnr,35)

if __name__=='__main__':unittest.main()
