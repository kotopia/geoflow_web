"""Offline only: no database or credential access."""
import argparse
import json
from pathlib import Path
from geoflow_ops.gis.business_messages import verify_messages


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--messages',type=Path,required=True)
    p.add_argument('--approval',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    result=verify_messages(args.messages.read_bytes(),json.loads(args.approval.read_text(encoding='utf-8')))
    with args.output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print('Original Messages IDs and exposed values match the approval candidate')


if __name__=='__main__':main()
