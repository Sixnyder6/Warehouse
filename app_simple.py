from flask import Flask, render_template_string

app = Flask(__name__)

DASHBOARD_HTML = """
<!DOCTYPE html><html><head><meta charset="utf-8"><title>Склад</title>
<style>
body{font-family:Arial;background:#f0f2f5;margin:0}
.nav{background:#1a1a2e;color:#fff;padding:15px;display:flex;justify-content:space-between}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;padding:20px}
.card{padding:20px;border-radius:10px;color:#fff}
.blue{background:#2196F3}.orange{background:#FF9800}.red{background:#f44336}.green{background:#4CAF50}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:10px}
th,td{padding:12px;border-bottom:1px solid #eee;text-align:left}
</style></head><body>
<div class="nav"><span>СКЛАД ЗАПЧАСТЕЙ</span><span>Иванов Иван (Кладовщик)</span></div>
<div class="cards">
<div class="card blue"><small>ТОВАРОВ</small><h1>156</h1></div>
<div class="card orange"><small>ЗАКАЗОВ</small><h1>3</h1></div>
<div class="card red"><small>МАЛО НА СКЛАДЕ</small><h1>5</h1></div>
<div class="card green"><small>ОПЕРАЦИЙ</small><h1>12</h1></div>
</div>
<div style="padding:20px">
<h2>Последние операции</h2>
<table><tr><th>Время</th><th>Сотрудник</th><th>Товар</th><th>Кол-во</th></tr>
<tr><td>14:32</td><td>Петров А.</td><td>Масляный фильтр</td><td style="color:red">-2</td></tr>
<tr><td>14:15</td><td>Сидоров В.</td><td>Антифриз 5л</td><td style="color:red">-1</td></tr>
<tr><td>13:58</td><td>Иванов И.</td><td>Приёмка: Колодки</td><td style="color:green">+20</td></tr>
</table></div></body></html>"""

@app.route('/')
@app.route('/desktop/dashboard')
def dashboard():
    return DASHBOARD_HTML

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000, debug=True)