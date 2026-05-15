import pandas as pd
df = pd.read_excel('productInfo_AMAZON.xlsx')
with open('temp.txt', 'w', encoding='utf-8') as f:
    for val in df['product_information'].dropna().tail(3).values:
        f.write(str(val) + '\n')
