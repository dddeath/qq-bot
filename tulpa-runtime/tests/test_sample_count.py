import sys,tempfile,unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'video'))
from sparse_overview import build_overview
class SampleCountTests(unittest.TestCase):
 def test_fragment_sampling_uses_requested_count_and_absolute_time(self):
  with tempfile.TemporaryDirectory() as t:
   def extract(video,time,path,remaining):Image.new('RGB',(64,32),'red').save(path);return True
   r=build_overview({'duration':120,'source':'x','frames':[]},Path(t)/'out',frame_count=4,start_seconds=60,end_seconds=80,extract=extract)
   self.assertEqual([x['time'] for x in r['selection']],[62.5,67.5,72.5,77.5]);self.assertEqual(len(r['images']),1)
