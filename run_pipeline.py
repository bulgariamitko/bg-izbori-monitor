"""Keep pulling pending videos until none are left. Rebuild dashboard after each.

Usage:
    python run_pipeline.py            # process all pending
    python run_pipeline.py --max 5    # stop after 5 videos
    python run_pipeline.py --once     # one and exit
"""
import argparse, traceback
import db, process_video, dashboard

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    db.init()
    done = 0
    while True:
        ok = process_video.process()
        if not ok:
            break
        done += 1
        try: dashboard.build()
        except Exception: traceback.print_exc()
        if args.once or (args.max and done >= args.max): break
    print(f"[run] processed {done} videos")

if __name__ == "__main__":
    main()
