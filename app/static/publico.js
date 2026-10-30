/* Reservared: formulario de reserva paso a paso. Sin dependencias. */
( function () {
	'use strict';

	var MESES = [ 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre' ];
	var DIAS_CORTOS = [ 'lu', 'ma', 'mi', 'ju', 'vi', 'sá', 'do' ];
	var DIAS_LARGOS = [ 'domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado' ];

	function el( tag, attrs, hijos ) {
		var n = document.createElement( tag );
		Object.keys( attrs || {} ).forEach( function ( k ) {
			if ( k === 'class' ) n.className = attrs[ k ];
			else if ( k === 'text' ) n.textContent = attrs[ k ];
			else if ( k.indexOf( 'on' ) === 0 ) n.addEventListener( k.slice( 2 ), attrs[ k ] );
			else if ( attrs[ k ] === true ) n.setAttribute( k, '' );
			else if ( attrs[ k ] !== false && attrs[ k ] != null ) n.setAttribute( k, attrs[ k ] );
		} );
		( hijos || [] ).forEach( function ( h ) {
			if ( h == null ) return;
			n.appendChild( typeof h === 'string' ? document.createTextNode( h ) : h );
		} );
		return n;
	}

	function pad( n ) { return ( n < 10 ? '0' : '' ) + n; }
	function iso( d ) { return d.getFullYear() + '-' + pad( d.getMonth() + 1 ) + '-' + pad( d.getDate() ); }
	function deIso( s ) { var p = s.split( '-' ); return new Date( +p[ 0 ], +p[ 1 ] - 1, +p[ 2 ] ); }
	function fechaLarga( s ) { var d = deIso( s ); return DIAS_LARGOS[ d.getDay() ] + ' ' + d.getDate() + ' de ' + MESES[ d.getMonth() ]; }
	function duracion( min ) {
		if ( min < 60 ) return min + ' min';
		var h = Math.floor( min / 60 ), m = min % 60;
		return h + ( h === 1 ? ' hora' : ' horas' ) + ( m ? ' ' + m + ' min' : '' );
	}

	function Agenda( raiz, cfg ) {
		this.raiz = raiz;
		this.cfg = cfg;
		this.paso = 'servicio';
		this.sel = { servicio: null, profesional: null, fecha: null, hora: null };
		this.mes = deIso( cfg.hoy );
		this.mes.setDate( 1 );
		this.dias = {};
		this.cargando = false;
		this.error = '';
		this.datos = { nombre: '', rut: '', email: '', telefono: '', notas: '', pagar: cfg.pagoModo !== 'ninguno' };
		this.resultado = null;
		if ( cfg.servicios.length === 1 ) this.sel.servicio = cfg.servicios[ 0 ];
		this.ajustarProfesional();
		this.paso = this.siguiente( 'inicio' );
		this.pintar();
	}

	Agenda.prototype.profesionalesDe = function ( servicio ) {
		return this.cfg.profesionales.filter( function ( p ) { return ! servicio || ! p.servicios || p.servicios.indexOf( servicio.id ) !== -1; } );
	};

	Agenda.prototype.pasos = function () {
		var p = [];
		if ( this.cfg.servicios.length > 1 ) p.push( [ 'servicio', 'Servicio' ] );
		if ( this.profesionalesDe( this.sel.servicio ).length > 1 ) p.push( [ 'profesional', 'Profesional' ] );
		p.push( [ 'fecha', 'Día y hora' ], [ 'datos', 'Tus datos' ] );
		return p;
	};

	// Con un solo profesional para el servicio, se elige solo.
	Agenda.prototype.ajustarProfesional = function () {
		var lista = this.profesionalesDe( this.sel.servicio );
		if ( lista.length === 1 ) this.sel.profesional = lista[ 0 ];
		else if ( this.sel.profesional && lista.indexOf( this.sel.profesional ) === -1 ) this.sel.profesional = null;
	};

	Agenda.prototype.siguiente = function ( desde ) {
		var orden = this.pasos().map( function ( p ) { return p[ 0 ]; } );
		if ( desde === 'inicio' ) return orden[ 0 ];
		return orden[ orden.indexOf( desde ) + 1 ] || desde;
	};

	Agenda.prototype.anterior = function () {
		var orden = this.pasos().map( function ( p ) { return p[ 0 ]; } );
		return orden[ orden.indexOf( this.paso ) - 1 ];
	};

	Agenda.prototype.ir = function ( paso ) {
		this.paso = paso;
		this.error = '';
		this.pintar();
		if ( paso === 'fecha' ) this.cargarMes();
		var top = this.raiz.getBoundingClientRect().top;
		if ( top < 0 ) this.raiz.scrollIntoView( { behavior: 'smooth', block: 'start' } );
	};

	Agenda.prototype.cargarMes = function () {
		var self = this;
		var desde = new Date( this.mes );
		var hasta = new Date( this.mes.getFullYear(), this.mes.getMonth() + 1, 0 );
		var url = this.cfg.api + 'disponibilidad?servicio=' + this.sel.servicio.id +
			'&profesional=' + ( this.sel.profesional ? this.sel.profesional.id : 0 ) +
			'&desde=' + iso( desde ) + '&hasta=' + iso( hasta );
		var clave = url;
		this.clave = clave;
		this.cargando = true;
		this.pintar();
		fetch( url, { credentials: 'same-origin' } )
			.then( function ( r ) { return r.json(); } )
			.then( function ( j ) {
				if ( self.clave !== clave ) return;
				self.dias = j.dias || {};
				self.cargando = false;
				if ( self.sel.fecha && ! self.dias[ self.sel.fecha ] ) { self.sel.fecha = null; self.sel.hora = null; }
				if ( ! self.sel.fecha ) {
					var primera = Object.keys( self.dias ).sort()[ 0 ];
					if ( primera ) self.sel.fecha = primera;
				}
				self.pintar();
			} )
			.catch( function () {
				self.cargando = false;
				self.error = 'No pudimos cargar las horas. Revisa tu conexión e intenta de nuevo.';
				self.pintar();
			} );
	};

	Agenda.prototype.resumen = function () {
		var s = this.sel, partes = [];
		if ( s.servicio ) partes.push( s.servicio.nombre );
		if ( this.profesionalesDe( s.servicio ).length > 1 && this.paso !== 'profesional' && this.paso !== 'servicio' ) {
			partes.push( s.profesional ? s.profesional.nombre : 'Cualquier profesional' );
		}
		if ( s.fecha && s.hora && this.paso === 'datos' ) partes.push( fechaLarga( s.fecha ) + ', ' + s.hora );
		return partes.length ? el( 'p', { class: 'ao-resumen', text: partes.join( ' · ' ) } ) : null;
	};

	Agenda.prototype.pintar = function () {
		var r = this.raiz;
		r.innerHTML = '';
		if ( this.resultado ) { r.appendChild( this.vistaListo() ); return; }

		var pasos = this.pasos(), actual = this.paso, idx = pasos.map( function ( p ) { return p[ 0 ]; } ).indexOf( actual );
		r.appendChild( el( 'ol', { class: 'ao-pasos', 'aria-label': 'Pasos de la reserva' }, pasos.map( function ( p, i ) {
			return el( 'li', { class: i < idx ? 'is-hecho' : ( i === idx ? 'is-actual' : '' ), 'aria-current': i === idx ? 'step' : false, text: p[ 1 ] } );
		} ) ) );
		r.appendChild( this.resumen() || document.createTextNode( '' ) );

		var cuerpo = this[ 'vista_' + actual ]();
		r.appendChild( cuerpo );

		if ( this.error ) r.appendChild( el( 'p', { class: 'ao-aviso ao-aviso--error', role: 'alert', text: this.error } ) );

		var atras = this.anterior();
		if ( atras ) {
			var self = this;
			r.appendChild( el( 'button', { type: 'button', class: 'ao-volver', text: '← Volver', onclick: function () { self.ir( atras ); } } ) );
		}
	};

	Agenda.prototype.vista_servicio = function () {
		var self = this;
		return el( 'div', { class: 'ao-lista' }, this.cfg.servicios.map( function ( s ) {
			var meta = duracion( s.duracion ) + ( s.online ? ' · online' : '' ) + ( s.precio ? ' · ' + s.precio : '' );
			return el( 'button', {
				type: 'button',
				class: 'ao-opcion' + ( self.sel.servicio && self.sel.servicio.id === s.id ? ' is-elegida' : '' ),
				onclick: function () {
					if ( ! self.sel.servicio || self.sel.servicio.id !== s.id ) { self.sel.fecha = null; self.sel.hora = null; }
					self.sel.servicio = s;
					self.ajustarProfesional();
					self.ir( self.siguiente( 'servicio' ) );
				}
			}, [
				el( 'span', { class: 'ao-opcion__nombre', text: s.nombre } ),
				el( 'span', { class: 'ao-opcion__meta', text: meta } ),
				s.descripcion ? el( 'span', { class: 'ao-opcion__desc', text: s.descripcion } ) : null
			] );
		} ) );
	};

	Agenda.prototype.vista_profesional = function () {
		var self = this;
		var opciones = [ { id: 0, nombre: 'Cualquier profesional', nota: 'Te mostramos todas las horas libres' } ].concat( this.profesionalesDe( this.sel.servicio ) );
		return el( 'div', { class: 'ao-lista' }, opciones.map( function ( p ) {
			var actual = self.sel.profesional ? self.sel.profesional.id : 0;
			return el( 'button', {
				type: 'button',
				class: 'ao-opcion' + ( actual === p.id && self.elegidoProfesional ? ' is-elegida' : '' ),
				onclick: function () {
					if ( actual !== p.id ) { self.sel.fecha = null; self.sel.hora = null; }
					self.sel.profesional = p.id ? p : null;
					self.elegidoProfesional = true;
					self.ir( 'fecha' );
				}
			}, [
				el( 'span', { class: 'ao-opcion__nombre', text: p.nombre } ),
				( p.nota || p.titulo ) ? el( 'span', { class: 'ao-opcion__meta', text: p.nota || p.titulo } ) : null
			] );
		} ) );
	};

	Agenda.prototype.vista_fecha = function () {
		var self = this;
		var hoy = deIso( this.cfg.hoy );
		var primerMes = new Date( hoy.getFullYear(), hoy.getMonth(), 1 );
		var limite = new Date( hoy ); limite.setDate( limite.getDate() + this.cfg.diasMaximo );
		var ultimoMes = new Date( limite.getFullYear(), limite.getMonth(), 1 );

		function mover( n ) {
			self.mes = new Date( self.mes.getFullYear(), self.mes.getMonth() + n, 1 );
			self.sel.fecha = null; self.sel.hora = null;
			self.cargarMes();
		}

		var cabecera = el( 'div', { class: 'ao-cal__cab' }, [
			el( 'button', { type: 'button', class: 'ao-cal__nav', 'aria-label': 'Mes anterior', disabled: this.mes <= primerMes, onclick: function () { mover( -1 ); }, text: '‹' } ),
			el( 'span', { class: 'ao-cal__mes', text: MESES[ this.mes.getMonth() ] + ' ' + this.mes.getFullYear() } ),
			el( 'button', { type: 'button', class: 'ao-cal__nav', 'aria-label': 'Mes siguiente', disabled: this.mes >= ultimoMes, onclick: function () { mover( 1 ); }, text: '›' } )
		] );

		var grilla = el( 'div', { class: 'ao-cal__grilla' + ( this.cargando ? ' is-cargando' : '' ) } );
		DIAS_CORTOS.forEach( function ( d ) { grilla.appendChild( el( 'span', { class: 'ao-cal__dow', text: d } ) ); } );
		var desfase = ( this.mes.getDay() + 6 ) % 7;
		for ( var i = 0; i < desfase; i++ ) grilla.appendChild( el( 'span' ) );
		var finMes = new Date( this.mes.getFullYear(), this.mes.getMonth() + 1, 0 ).getDate();
		for ( var dia = 1; dia <= finMes; dia++ ) {
			( function ( f ) {
				var libre = ! self.cargando && !! self.dias[ f ];
				grilla.appendChild( el( 'button', {
					type: 'button',
					class: 'ao-cal__dia' + ( libre ? ' is-libre' : '' ) + ( self.sel.fecha === f ? ' is-elegido' : '' ) + ( f === self.cfg.hoy ? ' is-hoy' : '' ),
					disabled: ! libre,
					'aria-pressed': self.sel.fecha === f ? 'true' : 'false',
					'aria-label': fechaLarga( f ) + ( libre ? '' : ', sin horas' ),
					onclick: function () { self.sel.fecha = f; self.sel.hora = null; self.pintar(); },
					text: String( deIso( f ).getDate() )
				} ) );
			} )( iso( new Date( this.mes.getFullYear(), this.mes.getMonth(), dia ) ) );
		}

		var horas;
		if ( this.cargando ) {
			horas = el( 'p', { class: 'ao-nota', text: 'Buscando horas libres…' } );
		} else if ( ! Object.keys( this.dias ).length ) {
			horas = el( 'p', { class: 'ao-nota', text: 'No quedan horas este mes. Prueba con el mes siguiente.' } );
		} else if ( ! this.sel.fecha ) {
			horas = el( 'p', { class: 'ao-nota', text: 'Elige un día marcado en el calendario.' } );
		} else {
			horas = el( 'div', {}, [
				el( 'p', { class: 'ao-horas__titulo', text: fechaLarga( this.sel.fecha ) } ),
				el( 'div', { class: 'ao-horas' }, this.dias[ this.sel.fecha ].map( function ( h ) {
					return el( 'button', {
						type: 'button',
						class: 'ao-hora' + ( self.sel.hora === h ? ' is-elegida' : '' ),
						onclick: function () { self.sel.hora = h; self.ir( 'datos' ); },
						text: h
					} );
				} ) )
			] );
		}

		return el( 'div', { class: 'ao-cal' }, [ el( 'div', { class: 'ao-cal__izq' }, [ cabecera, grilla ] ), el( 'div', { class: 'ao-cal__der' }, [ horas ] ) ] );
	};

	Agenda.prototype.vista_datos = function () {
		var self = this, d = this.datos, cfg = this.cfg, s = this.sel.servicio;

		function campo( id, etiqueta, tipo, extra ) {
			var attrs = Object.assign( { id: 'ao-' + id, name: id, type: tipo, value: d[ id ], oninput: function ( e ) { d[ id ] = e.target.value; } }, extra || {} );
			return el( 'div', { class: 'ao-campo' }, [ el( 'label', { for: 'ao-' + id, text: etiqueta } ), el( 'input', attrs ) ] );
		}

		var form = el( 'form', { class: 'ao-form', novalidate: true } );
		form.appendChild( campo( 'nombre', 'Nombre y apellido', 'text', { required: true, autocomplete: 'name' } ) );
		if ( cfg.pedirRut ) form.appendChild( campo( 'rut', 'RUT', 'text', { required: true, placeholder: '12.345.678-5', inputmode: 'text', autocomplete: 'off' } ) );
		form.appendChild( campo( 'email', 'Correo', 'email', { required: true, autocomplete: 'email' } ) );
		form.appendChild( campo( 'telefono', 'Teléfono', 'tel', { required: true, autocomplete: 'tel', placeholder: '+56 9 1234 5678' } ) );
		var notas = el( 'textarea', { id: 'ao-notas', name: 'notas', rows: '3', oninput: function ( e ) { d.notas = e.target.value; } } );
		notas.value = d.notas;
		form.appendChild( el( 'div', { class: 'ao-campo' }, [ el( 'label', { for: 'ao-notas', text: 'Comentario (opcional)' } ), notas ] ) );
		form.appendChild( el( 'div', { class: 'ao-trampa', 'aria-hidden': 'true' }, [ el( 'label', { for: 'ao-sitio', text: 'No llenar' } ), el( 'input', { id: 'ao-sitio', name: 'sitio_web', type: 'text', tabindex: '-1', autocomplete: 'off' } ) ] ) );

		var hayPago = cfg.pagoModo !== 'ninguno' && s.pago;
		var textoBoton = 'Reservar hora';
		if ( hayPago && cfg.pagoModo === 'opcional' ) {
			var chk = el( 'input', { id: 'ao-pagar', type: 'checkbox', checked: d.pagar, onchange: function ( e ) { d.pagar = e.target.checked; boton.textContent = d.pagar ? 'Reservar y pagar ' + s.pago : 'Reservar hora'; } } );
			form.appendChild( el( 'div', { class: 'ao-campo ao-campo--check' }, [ chk, el( 'label', { for: 'ao-pagar', text: ( cfg.pagoEsAbono ? 'Pagar ahora un abono de ' : 'Pagar ahora ' ) + s.pago + ' con Mercado Pago' } ) ] ) );
			textoBoton = d.pagar ? 'Reservar y pagar ' + s.pago : 'Reservar hora';
		} else if ( hayPago ) {
			form.appendChild( el( 'p', { class: 'ao-nota', text: ( cfg.pagoEsAbono ? 'Para confirmar la hora se paga un abono de ' : 'Para confirmar la hora se paga ' ) + s.pago + ' con Mercado Pago (débito o crédito).' } ) );
			textoBoton = 'Continuar al pago de ' + s.pago;
		}

		var boton = el( 'button', { type: 'submit', class: 'ao-boton', text: textoBoton } );
		form.appendChild( boton );

		form.addEventListener( 'submit', function ( e ) {
			e.preventDefault();
			if ( ! d.nombre.trim() ) return self.falla( 'Escribe tu nombre.', 'nombre' );
			if ( cfg.pedirRut && ! rutValido( d.rut ) ) return self.falla( 'El RUT no es válido. Escríbelo con dígito verificador, por ejemplo 12.345.678-5.', 'rut' );
			if ( ! /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test( d.email.trim() ) ) return self.falla( 'Revisa el correo: ahí te llega la confirmación.', 'email' );
			if ( ! d.telefono.trim() ) return self.falla( 'Escribe un teléfono de contacto.', 'telefono' );
			boton.disabled = true;
			boton.textContent = 'Reservando…';
			self.enviar( form.querySelector( '#ao-sitio' ).value );
		} );
		return form;
	};

	Agenda.prototype.falla = function ( msg, campo ) {
		this.error = msg;
		this.pintar();
		var input = this.raiz.querySelector( '#ao-' + campo );
		if ( input ) { input.setAttribute( 'aria-invalid', 'true' ); input.focus(); }
	};

	Agenda.prototype.enviar = function ( trampa ) {
		var self = this, d = this.datos, s = this.sel;
		fetch( this.cfg.api + 'reservas', {
			method: 'POST',
			credentials: 'same-origin',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify( {
				servicio_id: s.servicio.id,
				profesional_id: s.profesional ? s.profesional.id : 0,
				fecha: s.fecha,
				hora: s.hora,
				nombre: d.nombre,
				rut: d.rut,
				email: d.email.trim(),
				telefono: d.telefono,
				notas: d.notas,
				pagar: this.cfg.pagoModo === 'obligatorio' || ( this.cfg.pagoModo === 'opcional' && d.pagar ),
				sitio_web: trampa
			} )
		} )
			.then( function ( r ) { return r.json().then( function ( j ) { return { ok: r.ok, j: j }; } ); } )
			.then( function ( res ) {
				if ( ! res.ok ) {
					self.error = ( res.j && res.j.message ) || 'No se pudo reservar. Intenta de nuevo.';
					if ( res.j && res.j.code === 'ao_no_disponible' ) { s.hora = null; self.ir( 'fecha' ); self.error = res.j.message; self.pintar(); return; }
					self.pintar();
					return;
				}
				if ( res.j.pago_url ) {
					// Dentro de un iframe, el paso a Mercado Pago necesita un clic propio.
					if ( window.top === window ) { window.location.href = res.j.pago_url; return; }
					self.resultado = res.j;
					self.pintar();
					return;
				}
				self.resultado = res.j;
				self.pintar();
			} )
			.catch( function () {
				self.error = 'No se pudo conectar. Revisa tu conexión e intenta de nuevo.';
				self.pintar();
			} );
	};

	Agenda.prototype.vistaListo = function () {
		var r = this.resultado;
		if ( r.pago_url ) {
			return el( 'div', { class: 'ao-ficha ao-ficha--lista' }, [
				el( 'p', { class: 'ao-eyebrow', text: 'Falta el pago' } ),
				el( 'h3', { class: 'ao-ficha__titulo', text: r.cita.fecha } ),
				el( 'p', { text: r.cita.servicio + ' · con ' + r.cita.profesional } ),
				el( 'a', { class: 'ao-boton', href: r.pago_url, target: '_top', rel: 'noopener', text: 'Pagar con Mercado Pago' } )
			] );
		}
		return el( 'div', { class: 'ao-ficha ao-ficha--lista' }, [
			el( 'p', { class: 'ao-eyebrow', text: 'Hora reservada' } ),
			el( 'h3', { class: 'ao-ficha__titulo', text: r.cita.fecha } ),
			el( 'p', { text: r.cita.servicio + ' · con ' + r.cita.profesional } ),
			r.cita.sesion ? el( 'p', {}, [ 'Sesión online: ', el( 'a', { href: r.cita.sesion, target: '_blank', rel: 'noopener', text: r.cita.sesion } ) ] ) : ( r.cita.online ? el( 'p', { text: 'Es una sesión online: el enlace te llega por correo.' } ) : null ),
			r.aviso ? el( 'p', { class: 'ao-aviso', text: r.aviso } ) : null,
			el( 'p', { text: 'Te enviamos la confirmación a ' + this.datos.email.trim() + '. ' + ( r.mensaje || '' ) } ),
			r.enlace ? el( 'a', { class: 'ao-boton ao-boton--sec', href: r.enlace, target: '_top', text: 'Ver mi reserva' } ) : null
		] );
	};

	function rutValido( rut ) {
		var r = String( rut || '' ).replace( /[^0-9kK]/g, '' ).toUpperCase();
		if ( r.length < 2 ) return false;
		var dv = r.slice( -1 ), num = r.slice( 0, -1 ), suma = 0, mult = 2;
		if ( ! /^\d+$/.test( num ) ) return false;
		for ( var i = num.length - 1; i >= 0; i-- ) { suma += +num[ i ] * mult; mult = mult === 7 ? 2 : mult + 1; }
		var resto = 11 - ( suma % 11 );
		return ( resto === 11 ? '0' : resto === 10 ? 'K' : String( resto ) ) === dv;
	}

	function arrancar() {
		document.querySelectorAll( '.ao-agenda[data-config]' ).forEach( function ( raiz ) {
			try { new Agenda( raiz, JSON.parse( document.getElementById( raiz.getAttribute( 'data-config' ) ).textContent ) ); } catch ( e ) {
				raiz.innerHTML = '<p class="ao-aviso ao-aviso--error">No se pudo cargar la agenda.</p>';
			}
		} );
	}

	if ( document.readyState === 'loading' ) document.addEventListener( 'DOMContentLoaded', arrancar );
	else arrancar();

	// Dentro de un iframe, avisa su alto para que la página de WordPress no muestre barras.
	if ( window.parent !== window && window.ResizeObserver ) {
		new ResizeObserver( function () {
			window.parent.postMessage( { reservaredAlto: Math.ceil( document.documentElement.scrollHeight ) }, '*' );
		} ).observe( document.body );
	}
}() );
