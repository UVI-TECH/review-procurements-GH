#!/usr/bin/env python3
"""
Interfaz gráfica para la revisión de documentos de contratación — UNIAJC.
El usuario selecciona la carpeta de Contrataciones (sincronizada en el PC)
y dónde guardar el reporte. Reutiliza el motor de revisar_contrataciones.py.

IMPORTANTE antes de compilar:
  - Abre revisar_contrataciones.py y coloca tu API_KEY real.
  - Mantén ambos archivos en la misma carpeta al compilar.

Compilar a .exe:
  pip install pyinstaller anthropic openpyxl
  pyinstaller --onefile --windowed --name "RevisionContrataciones" revisar_contrataciones_gui.py
"""

import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import revisar_contrataciones as engine


def ejecutar(carpeta_raiz, archivo_excel, reportar):
    carpetas = sorted(c for c in Path(carpeta_raiz).iterdir() if c.is_dir())
    total = len(carpetas)
    filas = []
    for indice, carpeta in enumerate(carpetas, start=1):
        profesor = carpeta.name
        pdfs = sorted(carpeta.glob("*.pdf"))
        reportar(indice, total, profesor, len(pdfs))
        try:
            if not pdfs:
                filas.append(engine.fila_sin_documentos(profesor))
                continue
            resultados = []
            for pdf in pdfs:
                resultados.append(engine.analizar_con_reintentos(pdf, profesor))
                time.sleep(engine.PAUSA_ENTRE_LLAMADAS)
            engine.revalidar_por_cedula(resultados)
            filas.append(engine.construir_fila(profesor, resultados))
        except Exception as error:
            filas.append(engine.fila_error(profesor, error))
    Path(archivo_excel).parent.mkdir(parents=True, exist_ok=True)
    engine.escribir_excel(filas, archivo_excel)
    return filas


class App:
    def __init__(self, root):
        self.root = root
        self.cola = queue.Queue()
        root.title("Revisión de Contrataciones - UNIAJC")
        root.geometry("660x540")
        root.minsize(560, 480)
        self._construir_ui()

    def _construir_ui(self):
        marco = ttk.Frame(self.root, padding=16)
        marco.pack(fill="both", expand=True)

        ttk.Label(marco, text="Carpeta de Contrataciones (sincronizada en este PC):").pack(anchor="w")
        fila1 = ttk.Frame(marco)
        fila1.pack(fill="x", pady=(2, 4))
        self.entrada_carpeta = ttk.Entry(fila1)
        self.entrada_carpeta.pack(side="left", fill="x", expand=True)
        ttk.Button(fila1, text="Examinar...", command=self._elegir_carpeta).pack(side="left", padx=(8, 0))
        ttk.Label(marco, text="No pegues un enlace web de OneDrive: usa la carpeta sincronizada del Explorador.",
                  foreground="#666").pack(anchor="w", pady=(0, 10))

        ttk.Label(marco, text="Guardar reporte como:").pack(anchor="w")
        fila2 = ttk.Frame(marco)
        fila2.pack(fill="x", pady=(2, 12))
        self.entrada_salida = ttk.Entry(fila2)
        self.entrada_salida.pack(side="left", fill="x", expand=True)
        ttk.Button(fila2, text="Examinar...", command=self._elegir_salida).pack(side="left", padx=(8, 0))

        self.boton = ttk.Button(marco, text="Procesar", command=self._iniciar)
        self.boton.pack(pady=6)

        self.barra = ttk.Progressbar(marco, mode="determinate")
        self.barra.pack(fill="x", pady=(6, 2))
        self.estado = ttk.Label(marco, text="Listo")
        self.estado.pack(anchor="w")

        self.log = tk.Text(marco, height=12, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, pady=(8, 0))

    def _elegir_carpeta(self):
        ruta = filedialog.askdirectory(title="Selecciona la carpeta de Contrataciones")
        if ruta:
            self.entrada_carpeta.delete(0, "end")
            self.entrada_carpeta.insert(0, ruta)

    def _elegir_salida(self):
        ruta = filedialog.asksaveasfilename(
            title="Guardar reporte",
            defaultextension=".xlsx",
            initialfile="Reporte_Contrataciones.xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if ruta:
            self.entrada_salida.delete(0, "end")
            self.entrada_salida.insert(0, ruta)

    def _escribir_log(self, texto):
        self.log.configure(state="normal")
        self.log.insert("end", texto + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _iniciar(self):
        carpeta = self.entrada_carpeta.get().strip()
        salida = self.entrada_salida.get().strip()
        if carpeta.lower().startswith("http"):
            messagebox.showerror("Ruta inválida",
                                 "Selecciona la carpeta sincronizada en este PC, "
                                 "no un enlace web de OneDrive.")
            return
        if not carpeta or not Path(carpeta).is_dir():
            messagebox.showerror("Falta la carpeta", "Selecciona una carpeta de Contrataciones válida.")
            return
        if not salida:
            messagebox.showerror("Falta destino", "Indica dónde guardar el reporte.")
            return

        self.boton.configure(state="disabled")
        self.barra.configure(value=0)
        self._escribir_log("Iniciando...")
        threading.Thread(target=self._trabajar, args=(carpeta, salida), daemon=True).start()
        self.root.after(100, self._revisar_cola)

    def _trabajar(self, carpeta, salida):
        def reportar(indice, total, profesor, n_pdfs):
            self.cola.put(("progreso", indice, total, profesor, n_pdfs))
        try:
            filas = ejecutar(carpeta, salida, reportar)
            self.cola.put(("listo", filas, salida))
        except Exception as error:
            self.cola.put(("error", str(error)))

    def _revisar_cola(self):
        try:
            while True:
                self._procesar_evento(self.cola.get_nowait())
        except queue.Empty:
            pass
        if str(self.boton["state"]) == "disabled":
            self.root.after(100, self._revisar_cola)

    def _procesar_evento(self, evento):
        tipo = evento[0]
        if tipo == "progreso":
            _, indice, total, profesor, n_pdfs = evento
            porcentaje = indice * 100 // total if total else 0
            self.barra.configure(maximum=total, value=indice)
            self.estado.configure(text=f"{indice}/{total} ({porcentaje}%) - {profesor}")
            self._escribir_log(f"[{indice}/{total}] {porcentaje}% - {profesor}: {n_pdfs} PDF(s)")
        elif tipo == "listo":
            self._finalizar(evento[1], evento[2])
        elif tipo == "error":
            self.estado.configure(text="Error")
            self.boton.configure(state="normal")
            messagebox.showerror("Error", evento[1])

    def _finalizar(self, filas, salida):
        completos = sum(1 for f in filas if f["Estado"] == "COMPLETO")
        self.estado.configure(text="Completado")
        self._escribir_log(f"\nReporte generado: {salida}")
        self.boton.configure(state="normal")
        abrir = messagebox.askyesno(
            "Listo",
            f"Reporte generado.\n\nTotal: {len(filas)}\nCompletos: {completos}\n"
            f"Incompletos: {len(filas) - completos}\n\n¿Abrir el reporte ahora?",
        )
        if abrir:
            try:
                os.startfile(salida)
            except Exception:
                pass


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
