"""Review local calculation outcomes without changing the feature selection."""
from qgis.PyQt.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableWidget,QTableWidgetItem
from .result_highlight import ResultHighlight

class DepthResults(QDialog):
    def __init__(self, controller, layer, summary):
        super().__init__(controller.plugin.iface.mainWindow())
        self.layer,self.rows=layer,summary['results']
        self.highlight=ResultHighlight(controller.plugin.mapCanvas)
        self.setWindowTitle('심도 일괄계산 결과 · 서버 미저장')
        layout=QVBoxLayout(self)
        self.summary=QLabel(' · '.join(f'{label} {summary[key]}' for key,label in (
            ('total','전체 선택'),('success','계산 성공'),('changed','실제 변경'),
            ('unchanged','동일'),('skipped','건너뜀'),('failed','실패'))))
        layout.addWidget(self.summary)
        self.table=QTableWidget(len(self.rows),5,self)
        self.table.setHorizontalHeaderLabels(['객체','기존값','계산값','적용 결과','사유'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        labels={'changed':'편집 버퍼 변경','unchanged':'기존값과 동일','skipped':'기존값 유지','failed':'실패 · 기존값 유지'}
        for i,row in enumerate(self.rows):
            for j,v in enumerate((row['identity'],row['old'],row.get('depth'),labels[row['status']],
                                  row.get('reason') or ('음수 결과 검토 필요' if row.get('requires_review') else ''))):
                self.table.setItem(i,j,QTableWidgetItem('NULL' if v is None else str(v)))
        if self.rows: self.table.setCurrentCell(0,0)
        self.table.currentCellChanged.connect(lambda row,*args:self.locate(row))
        layout.addWidget(self.table)
        buttons=QHBoxLayout();layout.addLayout(buttons)
        for label,cb in (('변경 객체 전체 보기',self.show_changed),('강조 해제',self.highlight.clear),('닫기',self.accept)):
            b=QPushButton(label,self);b.clicked.connect(cb);buttons.addWidget(b)
        layout.addWidget(QLabel('변경값은 기존 저장 기능으로 저장하세요. 계산 성공은 서버 저장 성공이 아닙니다.'))
        self.finished.connect(self.highlight.clear)
        layer.destroyed.connect(self.reject)
        self.resize(900,420)
        self.highlight.show(layer,[dict(r,status='review') if r.get('requires_review') else r for r in self.rows if r['status'] in ('changed','failed')])
    def locate(self,row):
        if 0 <= row < len(self.rows): self.highlight.show(self.layer,[self.rows[row]],zoom=True)
    def show_changed(self):
        self.highlight.show(self.layer,[r for r in self.rows if r['status']=='changed'],zoom=True)
