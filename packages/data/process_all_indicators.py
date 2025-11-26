import argparse
import os
import sys
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.indicator_sync_pipeline import IndicatorSyncPipeline


def parse_arguments():
    parser = argparse.ArgumentParser(description="Sync indicator metadata and data from Excel definition.")
    parser.add_argument("--start-date", help="Fetch data starting from this date (YYYY-MM-DD).")
    parser.add_argument("--end-date", help="Fetch data up to this date (YYYY-MM-DD).")
    parser.add_argument("--requests-per-minute", type=int, default=30, help="FRED API request limit per minute.")
    parser.add_argument(
        "--default-start-date",
        default="2010-01-01",
        help="Fallback start date when database is empty.",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Delete existing data points for each indicator before fetching.",
    )
    return parser.parse_args()


def process_all_indicators(args):
    """
    Process all indicators from Excel file and fetch their data
    """
    engine = create_engine("sqlite:///fomc_data.db")
    Session = sessionmaker(bind=engine)
    session = Session()

    excel_file_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "docs",
        "US Economic Indicators with FRED Codes.xlsx",
    )

    pipeline = IndicatorSyncPipeline(
        session=session,
        excel_path=excel_file_path,
        requests_per_minute=args.requests_per_minute,
        default_start_date=args.default_start_date,
        start_date=args.start_date,
        end_date=args.end_date,
        full_refresh=args.full_refresh,
    )
    pipeline.run()
    session.close()


def main():
    args = parse_arguments()
    process_all_indicators(args)


if __name__ == "__main__":
    main()
