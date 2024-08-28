import argparse
import csv
import logging
import os
from datetime import datetime, date, timedelta
from decimal import *
from glob import glob

'''
Global data structures
'''
lot_roots = {}
lot_heads = {}
current_quantities = {}

'''
Chainable object which tracks a `Lot`. A new `Lot` is created by a `Buy` or similar transaction. A `Lot` is later finalized by a `Sell` transaction.
'''
class Lot:
    def __init__(self, prev_lot=None, instrument=None, purchase_date=None, purchase_price=None, quantity=None, sell_date=None, sell_price=None, next_lot=None):
        self.prev_lot = prev_lot
        self.instrument = instrument
        self.purchase_date = purchase_date
        self.purchase_price = purchase_price
        self.quantity = quantity
        self.sell_date = sell_date
        self.sell_price = sell_price
        self.next_lot = next_lot

    def __str__(self):
        return f'Instrument: {self.instrument}, Purchase Date: {self.purchase_date}, Purchase Price: {self.purchase_price}, Quantity: {self.quantity}, Sell Date: {self.sell_date}, Sell Price: {self.sell_price}'
    
    def split(self, first_lot_quantity):
        new_lot = Lot(self.prev_lot, self.instrument, self.purchase_date, self.purchase_price, first_lot_quantity, self.sell_date, self.sell_price, self)
        self.prev_lot = new_lot
        self.quantity -= first_lot_quantity
        self.sell_date = None
        self.sell_price = None
        return new_lot

'''
Process a directory of Robinhood transaction CSVs
'''
def import_directory(directory):
    filenames = os.listdir(directory)
    filenames.sort()
    for filename in filenames:
        filename = os.path.join(directory, filename)
        if os.path.isfile(filename):
            filename_root, extension = os.path.splitext(filename)
            if extension.lower() in [".csv"]:
                import_file(filename)

'''
Import a Robinhood transaction CSV
'''
def import_file(filename):
    logging.info(f'Importing {filename}')
    with open(filename, 'r', encoding='utf-8-sig') as file:
        try:
            reader = csv.DictReader(file)
            rows = list(reader)
            if 'Activity Date' not in rows[0]:
                raise ValueError('\'Activity Date\' missing')
        except:
            logging.warning(f'Failed to parse file: {filename}')
            return
        for row in reversed(rows): # Robinhood transaction files are in reversed order
            if row['Trans Code'] not in ['CONV', 'SXCH', 'MRGS', 'Sell', 'Buy', 'SPL']:
                continue
            if row['Instrument'] == '':
                continue
            try:
                transaction_date = datetime.strptime(row['Activity Date'], '%m/%d/%Y').date()
                instrument = row['Instrument']
                transaction_type = row['Trans Code']
                transaction_quantity = Decimal(row['Quantity'].strip('S')) # Strip the 'S' added to SXCH transactions
                transaction_price = row['Price'].strip('$').replace(',','')
                transaction_price = transaction_price if transaction_price == '' else Decimal(transaction_price)
            except:
                logging.error(f'Failed to parse row: {row}')
                quit()

            logging.debug(f'Processing {transaction_date} {instrument} {transaction_type} qty {transaction_quantity}')

            if transaction_type in ['CONV', 'SXCH', 'MRGS', 'Buy']:
                if transaction_type in ['CONV', 'SXCH', 'MRGS']:
                    transaction_price = 0 # Specifying worst-case cost basis of 0 since we don't have any more info (TODO can we get more info on MRGS?)
                lot = Lot(lot_heads.get(instrument), instrument, transaction_date, transaction_price, transaction_quantity)
                if instrument not in lot_roots:
                    lot_roots[instrument] = lot
                    current_quantities[instrument] = 0
                if lot_heads.get(instrument):
                    lot_heads[instrument].next_lot = lot
                lot_heads[instrument] = lot
                current_quantities[instrument] += transaction_quantity

            if transaction_type in ['Sell']:
                # Iterate from root until sell amount is fully distributed (FIFO)
                quantity_to_distribute = transaction_quantity
                current_lot = lot_roots[instrument]
                while quantity_to_distribute > 0:
                    if current_lot.sell_date: # Skip lots that have already been sold
                        current_lot = current_lot.next_lot
                        continue
                    current_lot.sell_date = transaction_date
                    current_lot.sell_price = transaction_price
                    if current_lot.quantity <= quantity_to_distribute:
                        # Lot is fully sold with this transaction, no need to split
                        quantity_to_distribute -= current_lot.quantity
                        current_lot = current_lot.next_lot
                    else:
                        # Lot is partially sold with this transaction, need to split
                        first_split_lot = current_lot.split(quantity_to_distribute)
                        quantity_to_distribute = 0
                        # Update chain to properly include newly created lot
                        if first_split_lot.prev_lot:
                            first_split_lot.prev_lot.next_lot = first_split_lot
                        else:
                            lot_roots[instrument] = first_split_lot
                current_quantities[instrument] -= transaction_quantity

            if transaction_type in ['SPL']:
                # transaction_quantity is the number of new shares 'received' as part of the split. Use it to calculate split_ratio.
                split_ratio = (current_quantities[instrument] + transaction_quantity) / current_quantities[instrument]
                logging.debug(f'Performing {instrument} split: current holdings of {current_quantities[instrument]} increased by {transaction_quantity} gives ratio {split_ratio}')
                if count_decimal_places(split_ratio) > 1: # As of 2024-08-27 there is a RH transaction reporting bug that limits SPL transaction values to 4 decimal places, leading to incorrect split ratio calculations
                    logging.warning(f'{instrument} split on {transaction_date} has a calculated ratio of {split_ratio} which seems wrong. Please enter the value you\'d like to use: ')
                    split_ratio = Decimal(input())
                    logging.info(f'Using split ratio of {split_ratio} for {instrument} split on {transaction_date}')
                # Iterate through all unsold lots, multiplying shares and dividing prices
                current_lot = lot_heads[instrument]
                while True:
                    if not current_lot.sell_date: # Found an unsold lot
                        current_lot.purchase_price /= split_ratio
                        current_lot.quantity *= split_ratio
                    else:
                        break
                    if current_lot.prev_lot:
                        current_lot = current_lot.prev_lot
                    else:
                        break
                current_quantities[instrument] *= split_ratio # Would simply add transaction_quantity, but as of 2024-08-27, the 4 decimal place bug may cause that number to be inaccurate

            logging.debug(f'Current quantity of {instrument}: {current_quantities[instrument]}')

'''
Helper function to count the number of decimal places in a number
'''
def count_decimal_places(num):
    num_str = str(num)
    if '.' in num_str:
        return len(num_str.split('.')[-1])
    else:
        return 0

'''
Helper function to format USD $ values to 2 decimal places
'''
def cur_str(num):
    if abs(num) < 0.005:
        return ''
    return f'{num:.2f}'

'''
Main script logic
'''
def main(args):
    refs = []
    for ref in args.transaction_file:
        new_refs = glob(ref) # Expand wildcards if not done already by the shell
        refs.extend(new_refs)
        if len(new_refs) == 0:
            logging.warning(f'Invalid file or directory: {ref}')

    # Import files / directories
    for ref in refs:
        if os.path.isfile(ref):
            import_file(ref)
        elif os.path.isdir(ref):
            import_directory(ref)
        else:
            logging.warning(f'Invalid file or directory: {ref}')
    
    # Generate CSV of all capital gains for the current year
    out_filename = 'out_gains.csv'
    logging.info(f'Writing {out_filename}')
    headers = ['Instrument', 'Long-Term Gains', 'Short-Term Gains']
    with open(out_filename, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        # Start at the HEADs of each instrument lot chain, iterate backwards until hitting a sold lot, then start counting profits per lot until hitting a lot sold prior to the current year
        start_of_year = date(date.today().year, 1, 1)
        combined_cap_gains_long = Decimal(0)
        combined_cap_gains_short = Decimal(0)
        for instrument in sorted(lot_heads.keys()):
            cap_gains_long = Decimal(0)
            cap_gains_short = Decimal(0)
            current_lot = lot_heads[instrument]
            while True:
                if current_lot.sell_date:
                    if current_lot.sell_date >= start_of_year:
                        lot_gain = (current_lot.sell_price - current_lot.purchase_price) * current_lot.quantity
                        if (current_lot.sell_date - current_lot.purchase_date) > timedelta(days=365):
                            cap_gains_long += lot_gain
                        else:
                            cap_gains_short += lot_gain
                    else:
                        break
                if current_lot.prev_lot:
                    current_lot = current_lot.prev_lot
                else:
                    break
            if cap_gains_long != 0 or cap_gains_short != 0:
                writer.writerow([instrument, cur_str(cap_gains_long), cur_str(cap_gains_short)])
            combined_cap_gains_long += round(cap_gains_long, 2)
            combined_cap_gains_short += round(cap_gains_short, 2)
        writer.writerow(['Total', cur_str(combined_cap_gains_long), cur_str(combined_cap_gains_short)])

    # Generate CSV of all lots adjusted for sells and splits
    out_filename = 'out_lots.csv'
    logging.info(f'Writing {out_filename}')
    headers = ['Instrument', 'Purchase Date', 'Purchase Price', 'Quantity', 'Sell Date', 'Sell Price']
    with open(out_filename, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        for instrument in sorted(lot_heads.keys()):
            lot = lot_roots[instrument]
            while lot:
                writer.writerow([lot.instrument, lot.purchase_date, lot.purchase_price, lot.quantity, lot.sell_date, lot.sell_price])
                lot = lot.next_lot

'''
Command line entry point
'''
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('transaction_file', nargs="+", help='Robinhood transaction CSV file or directory of CSV files')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()

    logging.basicConfig(
        format='%(asctime)s: %(levelname)s: %(message)s',
        level=logging.DEBUG if args.verbose else logging.INFO
    )
    
    main(args)
