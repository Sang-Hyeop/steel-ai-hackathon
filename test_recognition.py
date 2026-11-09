import unittest,io,tempfile,os,types,sys
from unittest.mock import patch
from pathlib import Path
from PIL import Image
import recognition
class OrientationTest(unittest.TestCase):
 def test_camera_rotation_and_matching_inference_size(self):
  im=Image.new('RGB',(40,20),'white')
  for x in range(10):
   for y in range(20):im.putpixel((x,y),(255,0,0))
  exif=Image.Exif();exif[274]=3;raw=io.BytesIO();im.save(raw,format='JPEG',exif=exif)
  captured={}
  class FakeModel:
   names={0:'wrench'}
   def predict(self,image,**kwargs):
    captured['image']=image;captured.update(kwargs)
    return [types.SimpleNamespace(boxes=None)]
  with tempfile.TemporaryDirectory() as d:
   weights=Path(d)/'fake.pt';weights.touch()
   with patch.dict(os.environ,{'STBM_MODEL_PATH':str(weights),'STBM_MODEL_IMGSZ':'320'}),patch.dict(sys.modules,{'ultralytics':types.SimpleNamespace(YOLO=lambda _:FakeModel())}):
    with patch.object(recognition,'_model',None),patch.object(recognition,'_path',None):recognition.recognize_image(raw.getvalue())
  self.assertEqual(captured['imgsz'],320)
  red=captured['image'].getpixel((35,10));white=captured['image'].getpixel((5,10))
  self.assertGreater(red[0],200);self.assertLess(red[1],60);self.assertGreater(white[1],200)
 def test_optional_decoder_failure_is_input_error(self):
  with tempfile.TemporaryDirectory() as d:
   weights=Path(d)/'fake.pt';weights.touch()
   with patch.dict(os.environ,{'STBM_MODEL_PATH':str(weights)}),patch('PIL.Image.open',side_effect=ModuleNotFoundError('optional decoder')):
    with self.assertRaises(ValueError):recognition.recognize_image(b'bad image')
if __name__=='__main__':unittest.main()
