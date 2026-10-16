import sys,tempfile,unittest,json
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'video'))
from sparse_overview import build_overview
class SparseOverviewTests(unittest.TestCase):
 def test_whole_timeline_uses_nearest_existing_frame_and_fills_empty_bins(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);source=p/'old.jpg';Image.new('RGB',(80,40),'blue').save(source)
   manifest={'duration':180,'source':'selected-p4.mp4','frames':[{'time':3,'file':str(source)},{'time':7,'file':str(source)},{'time':174,'file':str(source)}]}
   reads=[]
   def extract(video,time,path,remaining):
    self.assertEqual(video,'selected-p4.mp4');reads.append(time);Image.new('RGB',(80,40),'red').save(path);return True
   result=build_overview(manifest,p/'run',extract=extract)
   self.assertEqual(len(result['images']),2)
   self.assertEqual(len(result['selection']),18)
   self.assertEqual(result['selection'][0]['time'],3)
   self.assertEqual(result['selection'][-1]['time'],174)
   self.assertEqual(reads,[15,25,35,45,55,65,75,85,95,105,115,125,135,145,155,165])
   self.assertTrue(all(x['status']=='ok' for x in result['selection']))
   for item in result['images']:
    with Image.open(item['path']) as image:self.assertEqual(image.size,(1920,1140))
   with self.assertRaises(FileExistsError):build_overview(manifest,p/'run',extract=extract)
 def test_deadline_and_missing_frames_keep_time_slots_without_more_reads(self):
  with tempfile.TemporaryDirectory() as t:
   clock=[0];reads=[]
   def extract(video,time,path,remaining):reads.append(time);clock[0]=11;return False
   r=build_overview({'duration':180,'source':'v','frames':[]},Path(t)/'run',timeout_seconds=10,extract=extract,now=lambda:clock[0])
   self.assertEqual(reads,[5]);self.assertEqual(len(r['selection']),18)
   self.assertEqual(r['status'],'partial');self.assertTrue(all(x['status']=='missing' for x in r['selection']))
   self.assertEqual(len(r['images']),2)
 def test_invalid_sheet_budget_rejected_without_reading(self):
  with tempfile.TemporaryDirectory() as t:
   with self.assertRaises(ValueError):build_overview({'duration':180},Path(t)/'run',count=3,extract=lambda *a:self.fail())
 def test_chapter_range_samples_only_requested_interval_with_absolute_times(self):
  with tempfile.TemporaryDirectory() as t:
   calls=[]
   def extract(video,time,path,remaining):calls.append(time);Image.new('RGB',(80,40),'blue').save(path);return True
   r=build_overview({'duration':900,'source':'v','frames':[]},Path(t)/'run',count=1,start_seconds=600,end_seconds=690,extract=extract)
   self.assertEqual(calls,[605,615,625,635,645,655,665,675,685])
   self.assertEqual(r['range'],{'start_seconds':600,'end_seconds':690})
   self.assertEqual(len(r['images']),1)
if __name__=='__main__':unittest.main()
