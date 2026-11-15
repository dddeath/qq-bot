"""Incremental lexical/body-vector index refresh; preserve reviewed graph data."""
import argparse, hashlib, json, shutil, time
from pathlib import Path

def load(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def save(path, value): Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def refresh_index(source, store_path, output, encoder):
    import numpy as np
    from knowledge_ranking import tokenize
    source, output = Path(source), Path(output)
    if output.exists(): raise ValueError('index_output_already_exists')
    manifest = load(source/'index.json')
    if manifest['encoder']['fingerprint'] != encoder.identity['fingerprint']:
        raise ValueError('retrieval_encoder_identity_mismatch')
    data = load(store_path); original = load(source/'entries.json')['entries']; updated = data['entries']
    changed = {k for k,v in updated.items() if any(v.get(f) != original.get(k,{}).get(f)
        for f in ('revision','title','content','tags','collection','updated_at'))}
    # Existing graph evidence is tied to the source revision, never silently reattached.
    graph_entries = {n['entry_id'] for n in load(source/'nodes.json')}
    revised_graph = (changed & set(original) & graph_entries)
    if revised_graph: raise ValueError('reviewed_graph_revision_changed:'+','.join(sorted(revised_graph)))
    output.mkdir(parents=True)
    for name in ('nodes.json','nodes.npy','edges.json','edges.npy','edge-texts.json'):
        shutil.copyfile(source/name,output/name)
    tokens=load(source/'tokens.json');tags=load(source/'tag-tokens.json')
    for key in changed:
        item=updated[key];tokens[item['title']+'\n'+item['content']]=tokenize(item['title']+'\n'+item['content'])
    for key,tag in data['tags'].items():
        if key not in tags: tags[key]=tokenize(' '.join([tag.get('name',''),tag.get('description',''),*tag.get('aliases',[])]))
    old_chunks=load(source/'chunks.json');old_values=np.load(source/'chunks.npy',allow_pickle=False)
    keep=[i for i,c in enumerate(old_chunks) if c['entry_id'] not in changed]
    chunks=[old_chunks[i]for i in keep];vectors=[old_values[i]for i in keep];encodes=[]
    for key in sorted(changed):
        item=updated[key];text=item['content']
        if item['status']!='active': continue
        for start in range(0,len(text),300):
            part=text[start:start+360];vector,meta=encoder.run(part)
            chunks.append(dict(entry_id=key,revision=item['revision'],start=start,end=start+len(part),text=part));vectors.append(vector)
            encodes.append(dict(entry_id=key,start=start,end=start+len(part),meta=meta))
            if start+360>=len(text):break
    entries={**original,**updated};save(output/'entries.json',{'entries':entries});save(output/'tokens.json',tokens);save(output/'tag-tokens.json',tags);save(output/'chunks.json',chunks)
    np.save(output/'chunks.npy',np.asarray(vectors,dtype=np.float32))
    manifest.update(index_id=manifest['index_id']+'-store-'+digest(store_path)[:12],store_sha256=digest(store_path),
        graph_coverage=dict(reviewed_entries=len(graph_entries & set(updated)),not_built_entries=sorted(set(updated)-graph_entries),
                            policy='reuse_reviewed_graph_no_new_edges'))
    save(output/'index.json',manifest)
    record=dict(changed_entries=len(changed),added_entries=len(changed-set(original)),reused_chunks=len(keep),encoded_chunks=len(encodes),encodes=encodes,
        graph_unchanged=all(digest(source/n)==digest(output/n)for n in ('nodes.json','nodes.npy','edges.json','edges.npy','edge-texts.json')))
    save(output/'build-receipt.json',record)
    return record

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--store',required=True);p.add_argument('--output',required=True);p.add_argument('--encoder-root',required=True);a=p.parse_args()
    from knowledge_embedding import Encoder
    result=refresh_index(a.source,a.store,a.output,Encoder(a.encoder_root,'embedding'))
    print(json.dumps({k:v for k,v in result.items()if k!='encodes'}))
