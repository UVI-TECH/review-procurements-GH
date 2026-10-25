/* Revisión de Contrataciones: avisos ("toasts") y tooltips del tablero.
   Sin dependencias y compatible con la CSP de la app (ADR 0005): se carga desde
   static/, no usa eval ni innerHTML y el texto de los avisos entra con textContent. */
(function () {
  "use strict";

  var DURACION_MS = { success: 6000, info: 6000, warning: 9000, error: 12000 };

  function region() {
    return document.getElementById("avisos");
  }

  function cerrar(aviso) {
    if (!aviso.isConnected) return;
    window.clearTimeout(aviso._temporizador);
    aviso.classList.add("aviso-saliendo");
    window.setTimeout(function () {
      aviso.remove();
    }, 200);
  }

  function programarCierre(aviso) {
    window.clearTimeout(aviso._temporizador);
    aviso._temporizador = window.setTimeout(function () {
      cerrar(aviso);
    }, aviso._duracion);
  }

  function mostrar(nivel, texto) {
    var contenedor = region();
    if (!contenedor || !texto) return;
    nivel = DURACION_MS[nivel] ? nivel : "info";

    var aviso = document.createElement("div");
    aviso.className = "aviso-flotante aviso-" + nivel;
    var parrafo = document.createElement("p");
    parrafo.textContent = texto;
    var boton = document.createElement("button");
    boton.type = "button";
    boton.className = "aviso-cerrar";
    boton.setAttribute("aria-label", "Cerrar aviso");
    boton.textContent = "×";
    boton.addEventListener("click", function () {
      cerrar(aviso);
    });
    aviso.appendChild(parrafo);
    aviso.appendChild(boton);

    // Se pausa mientras el puntero o el foco están sobre el aviso (WCAG 2.2.1).
    aviso._duracion = DURACION_MS[nivel];
    aviso.addEventListener("mouseenter", function () {
      window.clearTimeout(aviso._temporizador);
    });
    aviso.addEventListener("mouseleave", function () {
      programarCierre(aviso);
    });
    aviso.addEventListener("focusin", function () {
      window.clearTimeout(aviso._temporizador);
    });
    aviso.addEventListener("focusout", function () {
      programarCierre(aviso);
    });

    contenedor.appendChild(aviso);
    programarCierre(aviso);
  }

  // Mensajes de Django de una página completa: el servidor los deja en una lista
  // visible (por si no hay JavaScript) y aquí pasan a la región aria-live.
  function avisosDelServidor() {
    var lista = document.getElementById("avisos-servidor");
    if (!lista) return;
    var pendientes = Array.prototype.map.call(lista.querySelectorAll("li"), function (li) {
      return [li.dataset.nivel, li.textContent.trim()];
    });
    lista.remove();
    // Un instante después de cargar, para que el lector de pantalla ya vigile la región.
    window.setTimeout(function () {
      pendientes.forEach(function (par) {
        mostrar(par[0], par[1]);
      });
    }, 150);
  }

  // Respuestas de HTMX: el servidor manda HX-Trigger: {"avisos": [{nivel, texto}, ...]}.
  // HTMX entrega un valor que no es objeto como detail.value.
  document.addEventListener("avisos", function (evento) {
    var lista = (evento.detail && evento.detail.value) || [];
    lista.forEach(function (a) {
      mostrar(a.nivel, a.texto);
    });
  });

  // Escape cierra el tooltip que está a la vista (WCAG 1.4.13) y el último aviso.
  document.addEventListener("keydown", function (evento) {
    if (evento.key !== "Escape") return;
    document.querySelectorAll(".col-tipo:hover, .col-tipo:focus-within").forEach(function (th) {
      th.classList.add("tooltip-cerrado");
    });
    var avisos = document.querySelectorAll(".aviso-flotante");
    if (avisos.length) cerrar(avisos[avisos.length - 1]);
  });
  // Vuelve a mostrarse la próxima vez que el puntero o el foco lleguen al encabezado.
  document.addEventListener(
    "mouseleave",
    function (evento) {
      var th = evento.target;
      if (th.classList && th.classList.contains("col-tipo")) th.classList.remove("tooltip-cerrado");
    },
    true
  );
  document.addEventListener("focusout", function (evento) {
    var th = evento.target.closest && evento.target.closest(".col-tipo");
    if (th) th.classList.remove("tooltip-cerrado");
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", avisosDelServidor);
  } else {
    avisosDelServidor();
  }
})();
