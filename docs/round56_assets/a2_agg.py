import json, numpy as np
R=[json.loads(l) for l in open('a2.jsonl')]
BINS=["0-14","15-29","30-59","60-99","100-149","150-199","200-255",">=256"]
M=np.zeros((6,6),np.int64); Mv=np.zeros((6,6),np.int64); B=np.zeros((8,7),np.int64)
cat=dict(n=0,only_a=0,only_b=0,both=0,neither=0)
for r in R:
    for k in cat: cat[k]+=r[k]
    for key,v in r['res'].items():
        M+=np.array(v['M']); Mv+=np.array(v['Mv']); B+=np.array(v['bins'])
print("пар:",len(R),"; пикселей в зонах перекрытия (сумма по парам):",cat['n'],cat)
tot=M.sum(); dis=tot-np.trace(M)
print("сравнено пикселей (пиксель в полигоне ровно одного из двух листов):",tot,"; различаются (финал):",dis,"=%.2f%%"%(100*dis/tot))
totv=Mv.sum(); disv=totv-np.trace(Mv)
print("то же по сегментации (veget, до маски обработки): различаются %d = %.2f%%"%(disv,100*disv/totv))
print("\nМатрица финальных классов, строки — «свой» лист (пиксель в его полигоне), столбцы — «чужой»; доля от всех различий, %:")
cls=['0','1','2','3','4','5']
print("      "+"".join(f"{c:>8}" for c in cls))
for i in range(6):
    print(f"  {i}   "+"".join((f"{100*M[i,j]/dis:8.2f}" if i!=j else "       -") for j in range(6)))
print("\nпары (неупорядоченные), % от различий:")
pr=sorted(((M[i,j]+M[j,i],i,j) for i in range(6) for j in range(i+1,6)),reverse=True)[:6]
for n,i,j in pr: print(f"  {i}↔{j}: {n} ({100*n/dis:.2f}%)")
print("\nСогласие по классам (диагональ) от пикселей класса «своего» листа, %:",{i:round(100*M[i,i]/M[i].sum(),2) for i in range(6) if M[i].sum()})
print("\nРасстояние до края холста «чужого» листа, пикс: пикселей / различаются % (финал) / различаются % (веге) / из различий: маска обработки % / сегментация % / различия с участием класса 5 %")
for k,b in enumerate(BINS):
    n,d,dv,mo,sg,i5,m5=B[k]
    if n: print(f"  {b:>8}: {n:>11} {100*d/n:6.2f}  {100*dv/n:6.2f}   {100*mo/d if d else 0:6.1f}  {100*sg/d if d else 0:6.1f}   {100*i5/d if d else 0:6.1f}")
n,d,dv,mo,sg,i5,m5=B.sum(axis=0)
print(f"  итого: {n} {100*d/n:.2f} {100*dv/n:.2f}  маска {100*mo/d:.1f}%  сегм. {100*sg/d:.1f}%  с классом 5: {100*i5/d:.1f}%")
print("С участием класса 5: из них только маска (веге совпала):",m5,"=%.1f%%"%(100*m5/i5),"; остальное — сегментация (+маска)",i5-m5)
