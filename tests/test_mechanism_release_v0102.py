"""TEST_ONLY: readable saved-report mechanism without invented numeric comparisons."""
from copy import deepcopy
import json,math,subprocess,tempfile,unittest
from pathlib import Path
from laboratory.presentation import build_presentation,render_svg
from laboratory.reader_infographic import layout,NO_COMPARISON
from laboratory import media_encoder


class MechanismReleaseTests(unittest.TestCase):
    def test_public_source_commit_is_retained_but_private_ids_and_secret_urls_are_redacted(self):
        from laboratory.reader_infographic import _clean
        commit='1cfe254e8d25b15f37048c3730134686abe60335'
        url='https://github.com/google-research/harness2/blob/'+commit+'/README.md'
        self.assertIn(url,_clean('Источник: '+url))
        self.assertIn('[ID скрыт]',_clean('Локальная запись '+('a'*32)))
        self.assertNotIn('https://example.org',_clean('https://example.org/file?api_key=private'))
        data=self.data();data['publication_sources']=[{'url':url}];data['sources']=[]
        _,parts=media_encoder._mechanism_layout(data,0)
        text=''.join(item[3] for item in parts if item[0]=='text')
        self.assertIn(commit,text);self.assertNotIn('[ID скрыт]',text)

    def fixture(self):
        url='https://research.example.org/method'
        steps=['Прочитать исходный документ и записать ограничения рабочей задачи.',
               'Проверить предложение по доступным источникам, сохранив основания и найденные противоречия.',
               'Передать проверенный результат человеку и сохранить урок с границами применения.']
        findings=['Для задачи A авторы сообщают +24%.','Для задачи B авторы сообщают +11%.','Для задачи C авторы сообщают +7%.']
        run={'id':'c'*32,'output':'TEST_ONLY: описание общего метода.\n'+'\n'.join(steps+findings)+'\n'+url,
             'links':[],'plan':{'sources':[{'id':'d'*32,'title':'TEST_ONLY: метод проверки документов','url':url}]}}
        review={'current':{'version':2,'body':{'editorial':{
            'title':'TEST_ONLY: проверка документов с сохранением оснований',
            'problem':'Документы требуют повторной проверки источников и ограничений.',
            'audience':'Команды, работающие с потоком документов.',
            'use_case':'Нужно подготовить проверяемый вывод для решения человека.',
            'mechanism':steps,'findings':findings,'limitations':['Перенос результата на другие документы не проверен.'],
            'resources':['Нужны доступ к источникам, хранилище и проверка человеком.'],
            'public_takeaway':'Оценить метод на своих документах с проверяемым критерием.',
            'next_step':'Выбрать небольшой набор ранее проверенных документов.',
            'comparisons':[]},'evidence':[{'id':'e1','source_url':url}]}}}
        return run,review,steps,url

    def data(self):
        run,review,_,_=self.fixture();return build_presentation(run,review)

    def test_manual_legacy_three_steps_use_reader_infographic_without_fabricated_pairs(self):
        run,review,steps,url=self.fixture();original=deepcopy((run,review))
        data=build_presentation(run,review)
        self.assertEqual((run,review),original)
        self.assertEqual(data['visual_theme'],'reader_infographic')
        self.assertEqual(data['visual']['kind'],'process_flow')
        self.assertEqual([item['text'] for item in data['visual']['steps']],steps)
        self.assertEqual(data['comparisons'],[])
        svg=render_svg(data)
        self.assertIn('Механизм по шагам',svg);self.assertIn(NO_COMPARISON,svg)
        self.assertIn(url,svg);self.assertNotIn('СРАВНЕНИЕ 1',svg)
        self.assertTrue(all(value in data['post_text'] for value in ('+24%','+11%','+7%')))
        _,parts=layout(data)
        self.assertFalse(any(item[0]=='ring' for item in parts))

    def test_manual_replay_tree_keeps_its_special_visual(self):
        run,review,_,_=self.fixture();review['current']['body']['editorial']['visual_kind']='replay_tree'
        data=build_presentation(run,review)
        self.assertEqual(data['visual']['kind'],'replay_tree')
        self.assertNotEqual(data.get('visual_theme'),'reader_infographic')

    def test_mechanism_panels_keep_full_steps_source_and_caption_at_native_size(self):
        data=self.data();original=deepcopy(data)
        _,_,steps,url=self.fixture()
        frames=[]
        for active in range(3):
            height,parts=media_encoder._mechanism_layout(data,active)
            all_text=' '.join(item[3] for item in parts if item[0]=='text')
            for text in steps+[data['title'],url,media_encoder.MECHANISM_CAPTION]:self.assertIn(text,all_text)
            self.assertIn(NO_COMPARISON,all_text)
            self.assertEqual(sum('СЕЙЧАС В СХЕМЕ' in item[3] for item in parts if item[0]=='text'),1)
            frame=media_encoder._mechanism_frame(data,active)
            self.assertEqual(frame.width,1080);self.assertEqual(height%2,0);self.assertLessEqual(height,1920)
            frames.append(frame)
        self.assertEqual(len({frame.size for frame in frames}),1)
        self.assertNotEqual(frames[0].tobytes(),frames[2].tobytes())
        self.assertEqual(data,original)

    def test_oversized_unclipped_mechanism_is_rejected_instead_of_shrinking_text(self):
        data=self.data()
        for step in data['visual']['steps']:step['text']='Полный шаг с доказательствами и ограничениями. '*90
        with self.assertRaisesRegex(ValueError,'не помещаются'):media_encoder._mechanism_frame(data,0)

    def test_mechanism_h264_roundtrip_is_nine_seconds_native_and_readable(self):
        binary=media_encoder.encoder_path()
        if binary is None:self.skipTest('Optional local H.264 encoder missing')
        from PIL import Image,ImageChops,ImageStat
        data=self.data();content=media_encoder.render_mp4(data)
        self.assertIsNotNone(content);self.assertIn(b'avc1',content);self.assertLess(len(content),8*1024*1024)
        expected=media_encoder._mechanism_frame(data,2)
        with tempfile.TemporaryDirectory() as directory:
            video=Path(directory)/'animation.mp4';last=Path(directory)/'last.png';video.write_bytes(content)
            result=subprocess.run([str(binary),'-hide_banner','-y','-sseof','-0.1','-i',str(video),'-frames:v','1',str(last)],capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertEqual(result.returncode,0)
            self.assertIn(b'Duration: 00:00:09.00',result.stderr)
            with Image.open(last) as actual:
                self.assertEqual(actual.size,expected.size);self.assertEqual(actual.width,1080)
                diff=ImageChops.difference(expected.convert('RGB'),actual.convert('RGB'))
                mse=sum(ImageStat.Stat(diff).sum2)/(expected.width*expected.height*3)
                self.assertGreater(10*math.log10(255**2/max(mse,1e-9)),35)


if __name__=='__main__':unittest.main()
