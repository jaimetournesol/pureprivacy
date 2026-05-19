// Command udprelay is the UDP-over-Tor relay shim described in
// docs/turn-udp-tor-shim.md.  Phase 1a: framed UDP↔TCP forwarding
// between two instances, optionally dialing the peer through a Tor
// SOCKS5 proxy.  coturn integration and OnionCat IPv6 addressing are
// deferred to Phase 1b/2.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

// dialer returns a fresh TCP connection to the peer udprelay, either
// via plain TCP (Phase 0 / local smoke) or through a Tor SOCKS5
// proxy (Phase 1).
type dialer func() (net.Conn, error)

func plainDialer(peer string, timeout time.Duration) dialer {
	return func() (net.Conn, error) {
		return net.DialTimeout("tcp", peer, timeout)
	}
}

func socks5Dialer(proxy, host string, port uint16, timeout time.Duration) dialer {
	return func() (net.Conn, error) {
		return dialSocks5(proxy, host, port, timeout)
	}
}

// udpToTCP listens for local UDP datagrams and ships each one, framed,
// onto a TCP connection to the peer.  The peer connection is
// established lazily on the first packet and re-established after any
// write error.  selfIP/peerIP populate the frame's address metadata —
// zeros are fine for Phase 1a's synthetic smoke test.
func udpToTCP(ctx context.Context, udpAddr string, dial dialer, selfIP, peerIP net.IP) error {
	laddr, err := net.ResolveUDPAddr("udp", udpAddr)
	if err != nil {
		return fmt.Errorf("resolve udp %q: %w", udpAddr, err)
	}
	conn, err := net.ListenUDP("udp", laddr)
	if err != nil {
		return fmt.Errorf("listen udp %q: %w", udpAddr, err)
	}
	defer conn.Close()
	log.Printf("udp→tcp: udp listen %s", udpAddr)

	var tcp net.Conn
	defer func() {
		if tcp != nil {
			tcp.Close()
		}
	}()

	buf := make([]byte, maxPayload)
	for {
		if err := ctx.Err(); err != nil {
			return nil
		}
		_ = conn.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
		n, raddr, err := conn.ReadFromUDP(buf)
		if err != nil {
			if ne, ok := err.(net.Error); ok && ne.Timeout() {
				continue
			}
			return fmt.Errorf("udp read: %w", err)
		}
		f := Frame{
			SrcIP:   selfIP,
			SrcPort: uint16(raddr.Port),
			DstIP:   peerIP,
			DstPort: 0, // Phase 1a — populated for real once coturn is wired in.
			Payload: append([]byte(nil), buf[:n]...),
		}
		for {
			if tcp == nil {
				tcp, err = dial()
				if err != nil {
					log.Printf("udp→tcp: dial peer: %v (will retry on next packet)", err)
					break
				}
				log.Printf("udp→tcp: connected to peer")
			}
			if err := writeFrame(tcp, f); err != nil {
				log.Printf("udp→tcp: write frame: %v (reconnecting)", err)
				tcp.Close()
				tcp = nil
				continue
			}
			break
		}
	}
}

// tcpToUDP accepts TCP connections on tcpAddr, decodes frames, and
// emits each payload as a UDP datagram to udpTarget.  One UDP socket
// is shared across all accepted connections; Phase 1a is point-to-
// point.
func tcpToUDP(ctx context.Context, tcpAddr, udpTarget string) error {
	target, err := net.ResolveUDPAddr("udp", udpTarget)
	if err != nil {
		return fmt.Errorf("resolve udp target %q: %w", udpTarget, err)
	}
	udp, err := net.DialUDP("udp", nil, target)
	if err != nil {
		return fmt.Errorf("dial udp target %q: %w", udpTarget, err)
	}
	defer udp.Close()

	ln, err := net.Listen("tcp", tcpAddr)
	if err != nil {
		return fmt.Errorf("listen tcp %q: %w", tcpAddr, err)
	}
	defer ln.Close()
	log.Printf("tcp→udp: tcp listen %s → udp %s", tcpAddr, udpTarget)

	go func() {
		<-ctx.Done()
		ln.Close()
	}()

	for {
		c, err := ln.Accept()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return nil
			}
			return fmt.Errorf("accept: %w", err)
		}
		go func(c net.Conn) {
			defer c.Close()
			log.Printf("tcp→udp: accepted from %s", c.RemoteAddr())
			for {
				f, err := readFrame(c)
				if err != nil {
					if err != io.EOF {
						log.Printf("tcp→udp: read frame: %v", err)
					}
					return
				}
				log.Printf("tcp→udp: recv %d bytes srcport=%d dstport=%d", len(f.Payload), f.SrcPort, f.DstPort)
				if _, err := udp.Write(f.Payload); err != nil {
					log.Printf("tcp→udp: udp write: %v", err)
					return
				}
			}
		}(c)
	}
}

// parseHostPort splits "host:port" with helpful error messages.
// Handles bracketed IPv6 and bare hostnames (including .onion).
func parseHostPort(hp string) (string, uint16, error) {
	host, portStr, err := net.SplitHostPort(hp)
	if err != nil {
		return "", 0, fmt.Errorf("not host:port: %w", err)
	}
	port64, err := strconv.ParseUint(portStr, 10, 16)
	if err != nil {
		return "", 0, fmt.Errorf("port %q not 1-65535", portStr)
	}
	return host, uint16(port64), nil
}

// parseIP returns the 16-byte IPv6 form of s, or zeros if s is empty.
// Used for the optional --self-ip / --peer-ip flags that populate
// frame metadata; zero values are fine for Phase 1a.
func parseIP(s string) (net.IP, error) {
	if s == "" {
		return make(net.IP, 16), nil
	}
	ip := net.ParseIP(s)
	if ip == nil {
		return nil, fmt.Errorf("not a valid IP: %q", s)
	}
	return ip.To16(), nil
}

func main() {
	udpListen := flag.String("udp-listen", "", "host:port to receive local UDP on")
	tcpListen := flag.String("tcp-listen", "", "host:port to receive remote frames on")
	peerTCP := flag.String("peer-tcp", "", "peer udprelay's tcp host:port (Phase 0 — direct TCP)")
	peerOnion := flag.String("peer-onion", "", "peer udprelay's onion host:port (Phase 1 — dialed via SOCKS5)")
	torSocks := flag.String("tor-socks", "tor:9050", "SOCKS5 proxy address for --peer-onion")
	udpTarget := flag.String("udp-target", "", "local UDP destination to emit decoded payloads to")
	selfIPStr := flag.String("self-ip", "", "this shim's IPv6 (frame metadata; ignored if empty)")
	peerIPStr := flag.String("peer-ip", "", "peer shim's IPv6 (frame metadata; ignored if empty)")
	dialTimeout := flag.Duration("dial-timeout", 30*time.Second, "TCP/SOCKS5 dial timeout")
	flag.Parse()

	if *udpListen == "" || *tcpListen == "" || *udpTarget == "" {
		fail("--udp-listen, --tcp-listen, and --udp-target are required")
	}
	if (*peerTCP == "") == (*peerOnion == "") {
		fail("exactly one of --peer-tcp or --peer-onion must be set")
	}

	selfIP, err := parseIP(*selfIPStr)
	if err != nil {
		fail("--self-ip: " + err.Error())
	}
	peerIP, err := parseIP(*peerIPStr)
	if err != nil {
		fail("--peer-ip: " + err.Error())
	}

	var dial dialer
	if *peerTCP != "" {
		log.Printf("peer: direct tcp %s", *peerTCP)
		dial = plainDialer(*peerTCP, *dialTimeout)
	} else {
		host, port, err := parseHostPort(*peerOnion)
		if err != nil {
			fail("--peer-onion: " + err.Error())
		}
		if !strings.HasSuffix(host, ".onion") {
			log.Printf("warn: --peer-onion host %q does not end in .onion; SOCKS5 dial will go through Tor anyway", host)
		}
		log.Printf("peer: socks5(%s) → %s:%d", *torSocks, host, port)
		dial = socks5Dialer(*torSocks, host, port, *dialTimeout)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sig
		log.Printf("shutting down")
		cancel()
	}()

	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		if err := udpToTCP(ctx, *udpListen, dial, selfIP, peerIP); err != nil {
			log.Printf("udp→tcp exited: %v", err)
			cancel()
		}
	}()
	go func() {
		defer wg.Done()
		if err := tcpToUDP(ctx, *tcpListen, *udpTarget); err != nil {
			log.Printf("tcp→udp exited: %v", err)
			cancel()
		}
	}()
	wg.Wait()
}

func fail(msg string) {
	fmt.Fprintln(os.Stderr, "udprelay: "+msg)
	fmt.Fprintln(os.Stderr, "usage: udprelay --udp-listen H:P --tcp-listen H:P --udp-target H:P (--peer-tcp H:P | --peer-onion H:P [--tor-socks H:P])")
	os.Exit(2)
}
