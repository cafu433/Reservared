/* Reservared: formulario de reserva paso a paso. Sin dependencias.
   Pasos: dónde (sucursal u online) → servicio → profesional (con filtro de
   especialidad) → día y hora → datos y pago. Los pasos con una sola opción se
   saltan solos. */
( function () {
	'use strict';

	var MESES = [ 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre' ];
	var DIAS_CORTOS = [ 'lu', 'ma', 'mi', 'ju', 'vi', 'sá', 'do' ];
	var DIAS_LARGOS = [ 'domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado' ];
	var NOMBRE_PASARELA = { webpay: 'Webpay (débito o crédito)', mercadopago: 'Mercado Pago' };

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
	function pesos( n ) { return '$' + String( Math.round( n ) ).replace( /\B(?=(\d{3})+(?!\d))/g, '.' ); }
	function duracion( min ) {
		if ( min < 60 ) return min + ' min';
		var h = Math.floor( min / 60 ), m = min % 60;
		return h + ( h === 1 ? ' hora' : ' horas' ) + ( m ? ' ' + m + ' min' : '' );
	}

	// Igual que app/precios.py: gana la tarifa que calza en más campos.
	function precioPara( s, modalidad, profesional, sucursal, especialidad ) {
		var mejor = s.precio, puntos = -1;
		s.tarifas.forEach( function ( t ) {
			var c = [ [ t.modalidad, modalidad ], [ t.especialidad, especialidad ], [ t.profesional, profesional ], [ t.sucursal, sucursal ] ];
			if ( c.some( function ( x ) { return x[ 0 ] && x[ 0 ] !== x[ 1 ]; } ) ) return;
			var p = c.filter( function ( x ) { return x[ 0 ]; } ).length;
			if ( p > puntos ) { mejor = t.precio; puntos = p; }
		} );
		return mejor;
	}

	function Agenda( raiz, cfg ) {
		this.raiz = raiz;
		this.cfg = cfg;
		this.sel = { lugar: null, servicio: null, especialidad: 0, profesional: null, fecha: null, hora: null };
		this.mes = deIso( cfg.hoy );
		this.mes.setDate( 1 );
		this.dias = {};
		this.cargando = false;
		this.error = '';
		this.datos = { nombre: '', rut: '', email: '', telefono: '', notas: '', pagar: cfg.pagoModo !== 'ninguno', pasarela: cfg.pasarelas[ 0 ] || '' };
		this.resultado = null;
		this.autoelegir();
		this.paso = this.pasos()[ 0 ][ 0 ];
		this.pintar();
	}

	/* ---------- Opciones de cada paso ---------- */

	Agenda.prototype.lugares = function () {
		var cfg = this.cfg, lugares = [];
		var hayPresencial = cfg.servicios.some( function ( s ) { return s.modalidades.indexOf( 'presencial' ) !== -1; } );
		var hayOnline = cfg.servicios.some( function ( s ) { return s.modalidades.indexOf( 'online' ) !== -1; } ) &&
			cfg.profesionales.some( function ( p ) { return p.modalidades.indexOf( 'online' ) !== -1; } );
		if ( hayPresencial ) {
			if ( cfg.sucursales.length ) {
				cfg.sucursales.forEach( function ( s ) { lugares.push( { clave: 's' + s.id, modalidad: 'presencial', sucursal: s.id, nombre: s.nombre, nota: s.direccion } ); } );
			} else {
				lugares.push( { clave: 'presencial', modalidad: 'presencial', sucursal: null, nombre: 'Presencial', nota: '' } );
			}
		}
		if ( hayOnline ) lugares.push( { clave: 'online', modalidad: 'online', sucursal: null, nombre: 'Online', nota: 'Videollamada: el enlace te llega por correo' } );
		return lugares;
	};

	Agenda.prototype.servicios = function () {
		var l = this.sel.lugar;
		return this.cfg.servicios.filter( function ( s ) { return ! l || s.modalidades.indexOf( l.modalidad ) !== -1; } );
	};

	Agenda.prototype.profesionalesDe = function ( conEspecialidad ) {
		var s = this.sel.servicio, l = this.sel.lugar, e = conEspecialidad === false ? 0 : this.sel.especialidad;
		return this.cfg.profesionales.filter( function ( p ) {
			if ( s && p.servicios && p.servicios.indexOf( s.id ) === -1 ) return false;
			if ( l && p.modalidades.indexOf( l.modalidad ) === -1 ) return false;
			if ( l && l.sucursal && p.sucursales.indexOf( l.sucursal ) === -1 && ! p.atiendeSinSucursal ) return false;
			if ( e && p.especialidades.indexOf( e ) === -1 ) return false;
			return true;
		} );
	};

	// Con una sola opción, se elige sola.
	Agenda.prototype.autoelegir = function () {
		var lugares = this.lugares();
		if ( lugares.length === 1 ) this.sel.lugar = lugares[ 0 ];
		var servicios = this.servicios();
		if ( servicios.length === 1 ) this.sel.servicio = servicios[ 0 ];
		else if ( this.sel.servicio && servicios.indexOf( this.sel.servicio ) === -1 ) this.sel.servicio = null;
		var profs = this.profesionalesDe( false );
		if ( profs.length === 1 ) this.sel.profesional = profs[ 0 ];
		else if ( this.sel.profesional && profs.indexOf( this.sel.profesional ) === -1 ) this.sel.profesional = null;
	};

	Agenda.prototype.pasos = function () {
		var p = [];
		if ( this.lugares().length > 1 ) p.push( [ 'lugar', 'Dónde' ] );
		if ( this.servicios().length > 1 || ! this.sel.lugar ) p.push( [ 'servicio', 'Servicio' ] );
		if ( this.profesionalesDe( false ).length > 1 || ! this.sel.servicio ) p.push( [ 'profesional', 'Profesional' ] );
		p.push( [ 'fecha', 'Día y hora' ], [ 'datos', 'Tus datos' ] );
		return p;
	};

	Agenda.prototype.siguiente = function ( desde ) {
		var orden = this.pasos().map( function ( p ) { return p[ 0 ]; } );
		return orden[ orden.indexOf( desde ) + 1 ] || 'fecha';
	};

	Agenda.prototype.anterior = function () {
		var orden = this.pasos().map( function ( p ) { return p[ 0 ]; } );
		return orden[ orden.indexOf( this.paso ) - 1 ];
	};

	Agenda.prototype.ir = function ( paso ) {
		this.paso = paso;
		this.error = '';
		this.pintar();
		if ( paso === 'fecha' ) { this.saltoMes = false; this.cargarMes(); }
		if ( this.raiz.getBoundingClientRect().top < 0 ) this.raiz.scrollIntoView( { behavior: 'smooth', block: 'start' } );
	};

	Agenda.prototype.precio = function () {
		var s = this.sel, l = s.lugar;
		if ( ! s.servicio ) return null;
		var modalidad = l ? l.modalidad : null, suc = l ? l.sucursal : null;
		if ( s.profesional ) return { exacto: true, monto: precioPara( s.servicio, modalidad, s.profesional.id, suc, s.especialidad || null ) };
		var montos = this.profesionalesDe().map( function ( p ) { return precioPara( s.servicio, modalidad, p.id, suc, s.especialidad || null ); } );
		if ( ! montos.length ) montos = [ precioPara( s.servicio, modalidad, null, suc, s.especialidad || null ) ];
		var min = Math.min.apply( null, montos ), max = Math.max.apply( null, montos );
		return { exacto: min === max, monto: min };
	};

	Agenda.prototype.textoPrecio = function () {
		var p = this.precio();
		if ( ! p || ! p.monto ) return '';
		return ( p.exacto ? '' : 'desde ' ) + pesos( p.monto );
	};

	Agenda.prototype.cargarMes = function () {
		var self = this, s = this.sel;
		var desde = new Date( this.mes );
		var hasta = new Date( this.mes.getFullYear(), this.mes.getMonth() + 1, 0 );
		var url = this.cfg.api + 'disponibilidad?servicio=' + s.servicio.id +
			'&profesional=' + ( s.profesional ? s.profesional.id : 0 ) +
			'&modalidad=' + ( s.lugar ? s.lugar.modalidad : '' ) +
			'&sucursal=' + ( s.lugar && s.lugar.sucursal ? s.lugar.sucursal : '' ) +
			'&especialidad=' + ( s.especialidad || '' ) +
			'&desde=' + iso( desde ) + '&hasta=' + iso( hasta );
		this.clave = url;
		this.cargando = true;
		this.pintar();
		fetch( url, { credentials: 'same-origin' } )
			.then( function ( r ) { return r.json(); } )
			.then( function ( j ) {
				if ( self.clave !== url ) return;
				self.dias = j.dias || {};
				self.cargando = false;
				// Si este mes ya no quedan horas, se pasa solo al siguiente (una vez).
				if ( ! Object.keys( self.dias ).length && ! self.saltoMes && iso( self.mes ).slice( 0, 7 ) === self.cfg.hoy.slice( 0, 7 ) ) {
					self.saltoMes = true;
					self.mes = new Date( self.mes.getFullYear(), self.mes.getMonth() + 1, 1 );
					self.cargarMes();
					return;
				}
				if ( s.fecha && ! self.dias[ s.fecha ] ) { s.fecha = null; s.hora = null; }
				if ( ! s.fecha ) s.fecha = Object.keys( self.dias ).sort()[ 0 ] || null;
				self.pintar();
			} )
			.catch( function () {
				self.cargando = false;
				self.error = 'No pudimos cargar las horas. Revisa tu conexión e intenta de nuevo.';
				self.pintar();
			} );
	};

	/* ---------- Pintar ---------- */

	Agenda.prototype.resumen = function () {
		var s = this.sel, partes = [];
		if ( s.lugar && this.paso !== 'lugar' ) partes.push( s.lugar.nombre );
		if ( s.servicio && this.paso !== 'servicio' && this.paso !== 'lugar' ) partes.push( s.servicio.nombre );
		if ( [ 'fecha', 'datos' ].indexOf( this.paso ) !== -1 && this.profesionalesDe( false ).length > 1 ) {
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
		var res = this.resumen();
		if ( res ) r.appendChild( res );
		r.appendChild( this[ 'vista_' + actual ]() );
		if ( this.error ) r.appendChild( el( 'p', { class: 'ao-aviso ao-aviso--error', role: 'alert', text: this.error } ) );
		var atras = this.anterior(), self = this;
		if ( atras ) r.appendChild( el( 'button', { type: 'button', class: 'ao-volver', text: '← Volver', onclick: function () { self.ir( atras ); } } ) );
	};

	Agenda.prototype.opcion = function ( elegida, nombre, meta, desc, alElegir ) {
		return el( 'button', { type: 'button', class: 'ao-opcion' + ( elegida ? ' is-elegida' : '' ), onclick: alElegir }, [
			el( 'span', { class: 'ao-opcion__nombre', text: nombre } ),
			meta ? el( 'span', { class: 'ao-opcion__meta', text: meta } ) : null,
			desc ? el( 'span', { class: 'ao-opcion__desc', text: desc } ) : null
		] );
	};

	Agenda.prototype.vista_lugar = function () {
		var self = this;
		return el( 'div', { class: 'ao-lista' }, this.lugares().map( function ( l ) {
			return self.opcion( self.sel.lugar && self.sel.lugar.clave === l.clave, l.nombre, l.nota, '', function () {
				if ( ! self.sel.lugar || self.sel.lugar.clave !== l.clave ) { self.sel.fecha = null; self.sel.hora = null; }
				self.sel.lugar = l;
				self.autoelegir();
				self.ir( self.siguiente( 'lugar' ) );
			} );
		} ) );
	};

	Agenda.prototype.vista_servicio = function () {
		var self = this, grupos = {}, orden = [];
		this.servicios().forEach( function ( s ) {
			var g = s.categoria || '';
			if ( ! grupos[ g ] ) { grupos[ g ] = []; orden.push( g ); }
			grupos[ g ].push( s );
		} );
		var cont = el( 'div', { class: 'ao-lista' } );
		orden.forEach( function ( g ) {
			if ( g && orden.length > 1 ) cont.appendChild( el( 'p', { class: 'ao-grupo', text: g } ) );
			grupos[ g ].forEach( function ( s ) {
				var l = self.sel.lugar;
				var precios = s.tarifas.filter( function ( t ) { return ! l || ! t.modalidad || t.modalidad === l.modalidad; } ).map( function ( t ) { return t.precio; } ).concat( [ s.precio ] );
				var min = Math.min.apply( null, precios ), max = Math.max.apply( null, precios );
				var meta = duracion( s.duracion ) + ( ! l && s.modalidades.length > 1 ? ' · presencial u online' : ( ! l && s.modalidades[ 0 ] === 'online' ? ' · online' : '' ) ) +
					( max ? ' · ' + ( min === max ? '' : 'desde ' ) + pesos( min ) : '' );
				cont.appendChild( self.opcion( self.sel.servicio === s, s.nombre, meta, s.descripcion, function () {
					if ( self.sel.servicio !== s ) { self.sel.fecha = null; self.sel.hora = null; }
					self.sel.servicio = s;
					self.autoelegir();
					self.ir( self.siguiente( 'servicio' ) );
				} ) );
			} );
		} );
		return cont;
	};

	Agenda.prototype.vista_profesional = function () {
		var self = this, cont = el( 'div', { class: 'ao-lista' } );
		var usadas = {};
		this.profesionalesDe( false ).forEach( function ( p ) { p.especialidades.forEach( function ( e ) { usadas[ e ] = true; } ); } );
		var esp = this.cfg.especialidades.filter( function ( e ) { return usadas[ e.id ]; } );
		if ( esp.length ) {
			var chips = el( 'div', { class: 'ao-chips', role: 'group', 'aria-label': 'Filtrar por especialidad' } );
			[ { id: 0, nombre: 'Todas' } ].concat( esp ).forEach( function ( e ) {
				chips.appendChild( el( 'button', { type: 'button', class: 'ao-chip' + ( self.sel.especialidad === e.id ? ' is-elegida' : '' ), 'aria-pressed': self.sel.especialidad === e.id ? 'true' : 'false', text: e.nombre, onclick: function () {
					self.sel.especialidad = e.id;
					if ( self.sel.profesional && self.profesionalesDe().indexOf( self.sel.profesional ) === -1 ) self.sel.profesional = null;
					self.pintar();
				} } ) );
			} );
			cont.appendChild( el( 'p', { class: 'ao-grupo', text: '¿Qué necesitas?' } ) );
			cont.appendChild( chips );
		}
		var lista = this.profesionalesDe();
		if ( ! lista.length ) {
			cont.appendChild( el( 'p', { class: 'ao-nota', text: 'Nadie atiende esa especialidad para este servicio. Prueba con otra.' } ) );
			return cont;
		}
		if ( lista.length > 1 ) {
			cont.appendChild( this.opcion( this.elegido && ! this.sel.profesional, 'Cualquier profesional', 'Te mostramos todas las horas libres', '', function () {
				self.sel.profesional = null; self.elegido = true; self.sel.fecha = null; self.sel.hora = null; self.ir( 'fecha' );
			} ) );
		}
		lista.forEach( function ( p ) {
			var nombres = self.cfg.especialidades.filter( function ( e ) { return p.especialidades.indexOf( e.id ) !== -1; } ).map( function ( e ) { return e.nombre; } );
			cont.appendChild( self.opcion( self.sel.profesional === p, p.nombre, p.titulo, nombres.join( ' · ' ), function () {
				if ( self.sel.profesional !== p ) { self.sel.fecha = null; self.sel.hora = null; }
				self.sel.profesional = p; self.elegido = true; self.ir( 'fecha' );
			} ) );
		} );
		return cont;
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
			self.saltoMes = true;
			self.cargarMes();
		}

		var cabecera = el( 'div', { class: 'ao-cal__cab' }, [
			el( 'button', { type: 'button', class: 'ao-cal__nav', 'aria-label': 'Mes anterior', disabled: this.mes <= primerMes, onclick: function () { mover( -1 ); }, text: '‹' } ),
			el( 'span', { class: 'ao-cal__mes', text: MESES[ this.mes.getMonth() ] + ' ' + this.mes.getFullYear() } ),
			el( 'button', { type: 'button', class: 'ao-cal__nav', 'aria-label': 'Mes siguiente', disabled: this.mes >= ultimoMes, onclick: function () { mover( 1 ); }, text: '›' } )
		] );

		var grilla = el( 'div', { class: 'ao-cal__grilla' + ( this.cargando ? ' is-cargando' : '' ) } );
		DIAS_CORTOS.forEach( function ( d ) { grilla.appendChild( el( 'span', { class: 'ao-cal__dow', text: d } ) ); } );
		for ( var i = 0; i < ( this.mes.getDay() + 6 ) % 7; i++ ) grilla.appendChild( el( 'span' ) );
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
		if ( this.cargando ) horas = el( 'p', { class: 'ao-nota', text: 'Buscando horas libres…' } );
		else if ( ! Object.keys( this.dias ).length ) horas = el( 'p', { class: 'ao-nota', text: 'No quedan horas este mes. Prueba con el mes siguiente.' } );
		else if ( ! this.sel.fecha ) horas = el( 'p', { class: 'ao-nota', text: 'Elige un día marcado en el calendario.' } );
		else {
			horas = el( 'div', {}, [
				el( 'p', { class: 'ao-horas__titulo', text: fechaLarga( this.sel.fecha ) } ),
				el( 'div', { class: 'ao-horas' }, this.dias[ this.sel.fecha ].map( function ( h ) {
					return el( 'button', { type: 'button', class: 'ao-hora' + ( self.sel.hora === h ? ' is-elegida' : '' ), onclick: function () { self.sel.hora = h; self.ir( 'datos' ); }, text: h } );
				} ) )
			] );
		}
		return el( 'div', { class: 'ao-cal' }, [ el( 'div', { class: 'ao-cal__izq' }, [ cabecera, grilla ] ), el( 'div', { class: 'ao-cal__der' }, [ horas ] ) ] );
	};

	Agenda.prototype.vista_datos = function () {
		var self = this, d = this.datos, cfg = this.cfg;

		function campo( id, etiqueta, tipo, extra ) {
			var attrs = Object.assign( { id: 'ao-' + id, name: id, type: tipo, value: d[ id ], oninput: function ( e ) { d[ id ] = e.target.value; } }, extra || {} );
			return el( 'div', { class: 'ao-campo' }, [ el( 'label', { for: 'ao-' + id, text: etiqueta } ), el( 'input', attrs ) ] );
		}

		var form = el( 'form', { class: 'ao-form', novalidate: true } );
		form.appendChild( campo( 'nombre', 'Nombre y apellido', 'text', { required: true, autocomplete: 'name' } ) );
		if ( cfg.pedirRut ) form.appendChild( campo( 'rut', 'RUT', 'text', { required: true, placeholder: '12.345.678-5', autocomplete: 'off' } ) );
		form.appendChild( campo( 'email', 'Correo', 'email', { required: true, autocomplete: 'email' } ) );
		form.appendChild( campo( 'telefono', 'Teléfono (WhatsApp)', 'tel', { required: true, autocomplete: 'tel', placeholder: '+56 9 1234 5678' } ) );
		var notas = el( 'textarea', { id: 'ao-notas', name: 'notas', rows: '3', oninput: function ( e ) { d.notas = e.target.value; } } );
		notas.value = d.notas;
		form.appendChild( el( 'div', { class: 'ao-campo' }, [ el( 'label', { for: 'ao-notas', text: 'Comentario (opcional)' } ), notas ] ) );
		form.appendChild( el( 'div', { class: 'ao-trampa', 'aria-hidden': 'true' }, [ el( 'label', { for: 'ao-sitio', text: 'No llenar' } ), el( 'input', { id: 'ao-sitio', name: 'sitio_web', type: 'text', tabindex: '-1', autocomplete: 'off' } ) ] ) );

		var precio = this.precio();
		var aPagar = precio && precio.monto ? Math.round( precio.monto * cfg.pagoPct / 100 ) : 0;
		if ( precio && precio.monto ) form.appendChild( el( 'p', { class: 'ao-total', text: 'Valor: ' + this.textoPrecio() } ) );

		var hayPago = cfg.pagoModo !== 'ninguno' && aPagar > 0;
		var boton = el( 'button', { type: 'submit', class: 'ao-boton' } );
		function textoBoton() {
			var pagar = hayPago && ( cfg.pagoModo === 'obligatorio' || d.pagar );
			boton.textContent = pagar ? ( cfg.pagoModo === 'obligatorio' ? 'Continuar al pago' : 'Reservar y pagar' ) : 'Reservar hora';
		}
		if ( hayPago ) {
			var abono = cfg.pagoPct < 100 ? 'un abono de ' + pesos( aPagar ) + ( precio.exacto ? '' : ' o más' ) : ( precio.exacto ? pesos( aPagar ) : 'el valor' );
			if ( cfg.pagoModo === 'opcional' ) {
				form.appendChild( el( 'div', { class: 'ao-campo ao-campo--check' }, [
					el( 'input', { id: 'ao-pagar', type: 'checkbox', checked: d.pagar, onchange: function ( e ) { d.pagar = e.target.checked; textoBoton(); pas.hidden = ! d.pagar; } } ),
					el( 'label', { for: 'ao-pagar', text: 'Pagar ahora ' + abono } )
				] ) );
			} else {
				form.appendChild( el( 'p', { class: 'ao-nota', text: 'Para confirmar la hora se paga ' + abono + ' en línea.' } ) );
			}
			var pas = el( 'fieldset', { class: 'ao-pasarelas' } );
			if ( cfg.pasarelas.length > 1 ) {
				pas.appendChild( el( 'legend', { text: 'Pagar con' } ) );
				cfg.pasarelas.forEach( function ( p ) {
					pas.appendChild( el( 'label', { class: 'ao-radio' }, [
						el( 'input', { type: 'radio', name: 'pasarela', value: p, checked: d.pasarela === p, onchange: function () { d.pasarela = p; } } ),
						NOMBRE_PASARELA[ p ] || p
					] ) );
				} );
				pas.hidden = cfg.pagoModo === 'opcional' && ! d.pagar;
				form.appendChild( pas );
			}
		}
		textoBoton();
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
		var self = this, d = this.datos, s = this.sel, cfg = this.cfg;
		fetch( cfg.api + 'reservas', {
			method: 'POST',
			credentials: 'same-origin',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify( {
				servicio_id: s.servicio.id,
				profesional_id: s.profesional ? s.profesional.id : 0,
				modalidad: s.lugar ? s.lugar.modalidad : '',
				sucursal_id: s.lugar && s.lugar.sucursal ? s.lugar.sucursal : '',
				especialidad_id: s.especialidad || '',
				fecha: s.fecha,
				hora: s.hora,
				nombre: d.nombre,
				rut: d.rut,
				email: d.email.trim(),
				telefono: d.telefono,
				notas: d.notas,
				pagar: cfg.pagoModo === 'obligatorio' || ( cfg.pagoModo === 'opcional' && d.pagar ),
				pasarela: d.pasarela,
				sitio_web: trampa
			} )
		} )
			.then( function ( r ) { return r.json().then( function ( j ) { return { ok: r.ok, j: j }; } ); } )
			.then( function ( res ) {
				if ( ! res.ok ) {
					if ( res.j && res.j.code === 'no_disponible' ) { s.hora = null; self.ir( 'fecha' ); }
					self.error = ( res.j && res.j.message ) || 'No se pudo reservar. Intenta de nuevo.';
					self.pintar();
					return;
				}
				if ( res.j.pago_url && window.top === window ) { window.location.href = res.j.pago_url; return; }
				self.resultado = res.j;
				self.pintar();
			} )
			.catch( function () {
				self.error = 'No se pudo conectar. Revisa tu conexión e intenta de nuevo.';
				self.pintar();
			} );
	};

	Agenda.prototype.vistaListo = function () {
		var r = this.resultado, c = r.cita;
		if ( r.pago_url ) {
			// Dentro de un iframe, el paso al pago necesita un clic propio.
			return el( 'div', { class: 'ao-ficha ao-ficha--lista' }, [
				el( 'p', { class: 'ao-eyebrow', text: 'Falta el pago' } ),
				el( 'h3', { class: 'ao-ficha__titulo', text: c.fecha } ),
				el( 'p', { text: c.servicio + ' · con ' + c.profesional } ),
				el( 'a', { class: 'ao-boton', href: r.pago_url, target: '_top', text: 'Pagar ' + r.pago_monto } )
			] );
		}
		return el( 'div', { class: 'ao-ficha ao-ficha--lista' }, [
			el( 'p', { class: 'ao-eyebrow', text: 'Hora reservada' } ),
			el( 'h3', { class: 'ao-ficha__titulo', text: c.fecha } ),
			el( 'p', { text: c.servicio + ' · con ' + c.profesional + ( c.precio ? ' · ' + c.precio : '' ) } ),
			c.lugar ? el( 'p', { text: 'Lugar: ' + c.lugar } ) : null,
			c.sesion ? el( 'p', {}, [ 'Sesión online: ', el( 'a', { href: c.sesion, target: '_blank', rel: 'noopener', text: c.sesion } ) ] ) : ( c.online ? el( 'p', { text: 'Es una sesión online: el enlace te llega por correo.' } ) : null ),
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
