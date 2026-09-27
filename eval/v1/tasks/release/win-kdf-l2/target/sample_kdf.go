// sample_kdf.go — #332 CONSTRUCTED eval target (family win-pe-kdf).
// NOT malware; no real data: every constant is seeded. Built with
// GOOS=windows GOARCH=amd64 CGO_ENABLED=0 (a real Windows PE).
// Recover the mod-SHA constants and re-implement kdf_derive (counter
// mode, two blocks). Under a debugger the sample CORRUPTS SILENTLY.
package main

import (
	"os"
	"syscall"
	"time"
	"unsafe"
)

// flattenStateRounds is the L2 flattener's dispatcher state anchor. The
// accessors are //go:noinline and the variable is package-level, so the
// gc must treat the state as opaque across the loop body's calls and
// cannot fold the switch back into straight-line code.
var flattenStateRounds int

//go:noinline
func flattenGetRounds() int { return flattenStateRounds }

//go:noinline
func flattenSetRounds(v int) { flattenStateRounds = v }

var modH = [...]uint32{
	0x09414046,
		0x30eddd4a,
		0x40f91cad,
		0xc48e119b,
		0xe5b9c1e4,
		0x7f3ff7f5,
		0xb29ad7ee,
		0x7b176cb4,
}

var modK = [...]uint32{
	0x2a356495, 0x6a998688, 0x4e08f8d4, 0x59eed09c,
		0x5c580acc, 0xc697b65e, 0x9c78de4b, 0xc851dd90,
		0xfe500c45, 0x545f5448, 0x410e1531, 0xaa2e3798,
		0x53919975, 0x87d9512f, 0x591e365a, 0x35832033,
		0x610122b4, 0xc139fc09, 0x8a1e96b9, 0x14c49ea3,
		0xabb09fbe, 0x7aba0b3b, 0x26d7360f, 0xa84cd3d7,
		0x9a8de81f, 0x72ca7bc6, 0xb2fc57d7, 0x03ff5818,
		0xeaf90122, 0x6933b4dc, 0xdbdbdf90, 0xd756de36,
		0x14465e0c, 0xcbf8da87, 0x443d6121, 0x56d98428,
		0xefd5901d, 0xf303ec62, 0x886c7589, 0xb1487eae,
		0x1cd94b74, 0x4ceda3b8, 0xa732a2b5, 0xf3c6cf78,
		0x32550318, 0x699e24a5, 0x7c9f1d56, 0x63051fe1,
		0xf2435259, 0xc555acbb, 0x78134ffd, 0x8f5f6cbe,
		0x99cd568c, 0x7bb1528d, 0x12f8e376, 0x30c97096,
		0xd162130f, 0xa1539bea, 0xa483ddc1, 0xf6396a1b,
		0x07c8cc15, 0xd774bf76, 0x3f7f5db8, 0xd9c0b185,
}

const (
	corruptMask = 0xdef429c38db4945d
	timingIters = 7467
	timingNs    = 4585960309
)

func rotr(x, n uint32) uint32 { return x>>n | x<<(32-n) }

func modSha256(msg []byte) [32]byte {
	var h [8]uint32
	copy(h[:], modH[:])
	buf := make([]byte, 64)
	bits := uint64(len(msg)) * 8
	copy(buf, msg)
	buf[len(msg)] = 0x80
	for i := len(msg) + 1; i < 56; i++ {
		buf[i] = 0
	}
	for i := 0; i < 8; i++ {
		buf[56+i] = byte(bits >> (56 - 8*i))
	}
	var w [64]uint32
	for i := 0; i < 16; i++ {
		w[i] = uint32(buf[4*i])<<24 | uint32(buf[4*i+1])<<16 |
			uint32(buf[4*i+2])<<8 | uint32(buf[4*i+3])
	}
	for i := 16; i < 64; i++ {
		s0 := rotr(w[i-15], 7) ^ rotr(w[i-15], 18) ^ w[i-15]>>3
		s1 := rotr(w[i-2], 17) ^ rotr(w[i-2], 19) ^ w[i-2]>>10
		w[i] = w[i-16] + s0 + w[i-7] + s1
	}
	a, b, c, d, e, f, g, hh := h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]
	for i := 0; i < 64; i++ {
		s1 := rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
		ch := e&f ^ ^e&g
		t1 := hh + s1 + ch + modK[i] + w[i]
		s0 := rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
		mj := a&b ^ a&c ^ b&c
		t2 := s0 + mj
		hh, g, f, e = g, f, e, d+t1
		d, c, b, a = c, b, a, t1+t2
	}
	h[0] += a
	h[1] += b
	h[2] += c
	h[3] += d
	h[4] += e
	h[5] += f
	h[6] += g
	h[7] += hh
	var out [32]byte
	for j := 0; j < 8; j++ {
		out[4*j] = byte(h[j] >> 24)
		out[4*j+1] = byte(h[j] >> 16)
		out[4*j+2] = byte(h[j] >> 8)
		out[4*j+3] = byte(h[j])
	}
	return out
}

// anti-debug (addition B): IsDebuggerPresent + CheckRemoteDebuggerPresent
// + NtQueryInformationProcess(ProcessDebugPort) + a timing gate. Response:
// silent corruption (output XOR corruptMask).
func corruptState() uint64 {
	kernel32 := syscall.NewLazyDLL("kernel32.dll")
	ntdll := syscall.NewLazyDLL("ntdll.dll")
	idp := kernel32.NewProc("IsDebuggerPresent")
	crdp := kernel32.NewProc("CheckRemoteDebuggerPresent")
	ntqip := ntdll.NewProc("NtQueryInformationProcess")
	hit := false
	if r, _, _ := idp.Call(); r != 0 {
		hit = true
	}
	var dbg int32
	if r, _, _ := crdp.Call(uintptr(0xffffffffffffffff),
		uintptr(unsafe.Pointer(&dbg))); r != 0 && dbg != 0 {
		hit = true
	}
	var port uint64
	ntqip.Call(uintptr(0xffffffffffffffff), 7,
		uintptr(unsafe.Pointer(&port)), 8, 0)
	if port != 0 {
		hit = true
	}
	t0 := time.Now()
	s := uint32(0)
	for i := 0; i < timingIters; i++ {
		s += uint32(i)
	}
	_ = s
	if time.Since(t0) > time.Duration(timingNs)*time.Nanosecond {
		hit = true
	}
	if hit {
		return corruptMask
	}
	return 0
}

func main() {
	in := make([]byte, 32)
	os.Stdin.Read(in)
	mask := corruptState()
	out := make([]byte, 64)
	var cat []byte
	var dig [32]byte
	
/* flatten-begin rounds (flattened: OLLVM-style switch dispatcher; noinline state accessors = optimizer-resistant) */
	i := 0
	flattenSetRounds(0)
	rounds:
	for {
		switch flattenGetRounds() {
		case 0:
			if i < 2 {
				cat = append(in, byte(i), 0, 0, 0)
				flattenSetRounds(1)
			} else {
				break rounds
			}
		case 1:
			dig = modSha256(cat)
			flattenSetRounds(2)
		case 2:
			copy(out[32*i:], dig[:])
			i++
			flattenSetRounds(0)
		}
	}
/* flatten-end */
	if mask != 0 {
		for i := range out {
			out[i] ^= byte(mask >> (8 * (i % 8)))
		}
	}
	os.Stdout.Write(out)
	syscall.Exit(0)
}
