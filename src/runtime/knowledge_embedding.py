import os
import hashlib
import json
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('TOKENIZERS_PARALLELISM','false')
from pathlib import Path
from time import perf_counter
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

ASCII_LOWER = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')
EMBEDDING_IDENTITY = dict(
    repository='Xenova/bge-base-zh-v1.5',
    revision='71e50dc531959f9e04ebf190ea25b00261a0a186',
    weight='model.onnx',
    model_sha256='5e5619f7cca7380b824d329c157dba10bee7cc00d0c139e82fdb7906051b8e4f',
    tokenizer_sha256='7dfbf1966ebf99d471c3796e9b457329d2b2182b817e144f1e904b957745c839',
    dimensions=768, precision='fp32', normalization='ascii-lower-v1',
    query_prefix='为这个句子生成表示以用于检索相关文章：', pooling='cls-l2', max_tokens=512)
EMBEDDING_IDENTITY['fingerprint'] = hashlib.sha256(
    json.dumps(EMBEDDING_IDENTITY, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()

def normalize_embedding_text(text):
    return text.translate(ASCII_LOWER)

class Encoder:
    def __init__(self, root, kind):
        t=perf_counter(); self.kind=kind
        p=Path(root)/'models'/kind
        self.identity = dict(EMBEDDING_IDENTITY) if kind == 'embedding' else None
        weight=EMBEDDING_IDENTITY['weight'] if kind=='embedding' else 'model_quint8_avx2.onnx'
        if self.identity:
            for name, expected in ((weight, self.identity['model_sha256']),
                                   ('tokenizer.json', self.identity['tokenizer_sha256'])):
                if file_sha256(p/name) != expected:
                    raise ValueError('embedding_artifact_mismatch: '+name)
        self.tokenizer=Tokenizer.from_file(str(p/'tokenizer.json'))
        self.tokenizer.no_padding()
        self.tokenizer.enable_truncation(max_length=512)
        opts=ort.SessionOptions(); opts.intra_op_num_threads=1; opts.inter_op_num_threads=1
        opts.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        opts.enable_cpu_mem_arena=False
        opts.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session=ort.InferenceSession(str(p/weight),opts,providers=['CPUExecutionProvider'])
        self.inputs=[x.name for x in self.session.get_inputs()]
        self.outputs=[x.name for x in self.session.get_outputs()]
        self.load_seconds=perf_counter()-t

    def run(self,text,pair=None,query=False):
        t=perf_counter()
        normalized=False
        if self.kind=='embedding':
            value=normalize_embedding_text(text)
            normalized=value!=text
            text=value
            if pair is not None:
                value=normalize_embedding_text(pair)
                normalized=normalized or value!=pair
                pair=value
        if query and self.kind=='embedding': text=self.identity['query_prefix']+text
        encoded=self.tokenizer.encode(text,pair)
        available={'input_ids':encoded.ids,'attention_mask':encoded.attention_mask,'token_type_ids':encoded.type_ids}
        values=self.session.run(None,{n:np.array([available[n]],dtype=np.int64) for n in self.inputs})
        if self.kind=='embedding':
            vector=values[0][0,0,:] if values[0].ndim==3 else values[0][0]
            vector=vector/(np.linalg.norm(vector)+1e-12)
            result=vector.astype(np.float32)
            if result.shape != (self.identity['dimensions'],) or not np.isfinite(result).all():
                raise ValueError('embedding_output_mismatch')
        else: result=float(values[0].reshape(-1)[0])
        return result, {'seconds':perf_counter()-t,'tokens':len(encoded.ids),
                        'truncated':bool(encoded.overflowing),'input_characters':len(text)+(len(pair) if pair else 0),
                        'normalization':'ascii-lower-v1' if self.kind=='embedding' else 'unchanged',
                        'normalization_changed':normalized,
                        **({'encoder': dict(self.identity)} if self.identity else {})}

    def embed(self,text,query=False): return self.run(text,query=query)[0]

    def rank(self,query,documents):
        t=perf_counter(); results=[]
        for d in documents:
            score,meta=self.run(query,d)
            results.append({'score':score,**meta})
        return results,perf_counter()-t
