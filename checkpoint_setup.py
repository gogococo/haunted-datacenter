#!/usr/bin/env python3
"""Prepare a local runner receipt from a completed job and a dashboard download.
Reads Token Factory metadata; does not submit training or create an endpoint.
"""
import argparse,hashlib,json,shutil,struct
from pathlib import Path
import content,tokenfactory as tf

def prepare(job_id,weights,base_dir,output_dir,seed):
 job=tf.api('/v1/fine_tuning/jobs/'+job_id)
 if job['status']!='succeeded':raise ValueError('The training job must have succeeded.')
 checkpoint=max(tf.api('/v1/fine_tuning/jobs/'+job_id+'/checkpoints')['data'],key=lambda row:row['step_number'])
 files=[tf.api('/v1/files/'+fid) for fid in checkpoint['result_files']]
 weight_info=next(row for row in files if Path(row['filename']).name=='adapter_model.safetensors')
 config_info=next(row for row in files if Path(row['filename']).name=='adapter_config.json')
 weights=Path(weights);base_dir=Path(base_dir).resolve();output_dir=Path(output_dir).resolve()
 if not (base_dir/'config.json').is_file():raise ValueError('Download the matching base model first.')
 if weights.stat().st_size!=weight_info['bytes']:raise ValueError('Weight file size does not match the final checkpoint.')
 with weights.open('rb') as file:
  length=struct.unpack('<Q',file.read(8))[0]
  if length>10000000:raise ValueError('Invalid safetensors header.')
  json.loads(file.read(length))
 config=tf.api('/v1/files/'+config_info['id']+'/content')
 if config.get('base_model_name_or_path')!=job['model']:raise ValueError('Checkpoint configuration and training model differ.')
 recipe=content.recipe_hash(Path(seed).read_text())
 output_dir.mkdir(parents=True,exist_ok=True)
 dest=output_dir/'adapter_model.safetensors'
 if weights.resolve()!=dest:shutil.copy2(weights,dest)
 (output_dir/'adapter_config.json').write_text(json.dumps(config,indent=2)+'\n')
 receipt={'job_id':job_id,'checkpoint_id':checkpoint['id'],'model':job['model'],'training_file':job['training_file'],
          'validation_file':job['validation_file'],'base_dir':str(base_dir),'adapter_dir':str(output_dir),
          'recipe_hash':recipe,'provenance':'Dashboard download selected by the host; final-checkpoint metadata and size verified. No cloud checksum is available.',
          'files':[{'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                   for p in (dest,output_dir/'adapter_config.json')]}
 path=output_dir/'receipt.json';path.write_text(json.dumps(receipt,indent=2)+'\n');return path

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--job',required=True);p.add_argument('--weights',required=True);p.add_argument('--base-dir',required=True)
 p.add_argument('--output-dir',default=str(content.ROOT/'.runtime/caretaker'));p.add_argument('--seed',default=str(content.ROOT/'solutions/seed-clean.jsonl'));args=p.parse_args()
 print(prepare(args.job,args.weights,args.base_dir,args.output_dir,args.seed))

if __name__=='__main__':main()
