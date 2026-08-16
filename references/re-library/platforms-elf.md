# ELF Binary Deep-Analysis Reference

> Structure parsing, anti-analysis adversary identification, and analysis techniques for reversing Linux/Android ELF files.

---

## ELF structure quick reference

### File header (ELF Header)

```text
Offset Size Field              Notes
0x00  4    e_ident[EI_MAG]   Magic: 7f 45 4c 46 ("\x7fELF")
0x04  1    e_ident[EI_CLASS] 1=32bit, 2=64bit
0x05  1    e_ident[EI_DATA]  1=LE, 2=BE
0x10  2    e_type            2=EXEC, 3=DYN(PIE/SO), 4=CORE
0x12  2    e_machine         0x03=x86, 0x3E=x86_64, 0xB7=AArch64, 0x28=ARM
0x18  8    e_entry           entry-point virtual address
0x20  8    e_phoff           program header table offset
0x28  8    e_shoff           section header table offset (may be 0 when stripped)
0x38  2    e_phnum           number of program headers
0x3C  2    e_shnum           number of section headers
```

### Program headers

```text
Value  Name       Notes
0x01   PT_LOAD    loadable segment (code/data)
0x02   PT_DYNAMIC dynamic-linking information
0x03   PT_INTERP  interpreter path (/lib/ld-linux.so)
0x04   PT_NOTE    auxiliary information
0x06   PT_PHDR    the program header table itself
0x6474e550 PT_GNU_EH_FRAME  exception handling
0x6474e551 PT_GNU_STACK     stack-executable flag
0x6474e552 PT_GNU_RELRO     read-only relocations
```

### Common sections

| Section | Notes |
|------|------|
| `.text` | code segment |
| `.rodata` | read-only data (string constants) |
| `.data` | initialized globals |
| `.bss` | uninitialized globals |
| `.plt` / `.got` | dynamic-linking jump tables |
| `.init_array` | array of constructor pointers |
| `.fini_array` | array of destructor pointers |
| `.dynamic` | dynamic-linking information |
| `.symtab` / `.dynsym` | symbol tables |
| `.strtab` / `.dynstr` | string tables |

---

## Recognizing anti-analysis tricks

### Common ELF anti-analysis techniques

| Technique | Trait | Countermeasure |
|------|------|---------|
| Corrupted program headers | PHDR filled with garbage (e.g., 0x0a) | Repair manually or ignore the corrupted PHDR |
| No section headers | `e_shoff = 0`, `e_shnum = 0` | Rely on program headers only, not sections |
| Stripped symbols | No `.symtab`, function names all gone | GoReSym (Go) / signature matching / FLIRT |
| Static linking | No `.dynamic`, huge size | Identify library functions with FLIRT/Lumina |
| File-type masquerading | Extensions .sh/.txt/.jpg | Judge with the `file` command / magic bytes |
| UPX packing | Contains `UPX!` markers | Unpack with `upx -d` |
| Custom packer | Entry point jumps to unpacking code | Run dynamically to the OEP, then dump |
| Anti-debugging | ptrace(TRACEME) | LD_PRELOAD hook / patch |
| Anti-VM | Reads /proc/cpuinfo | Modify cpuinfo or hook the read |
| Encrypted code | Decrypts .text at runtime | Breakpoint after decryption and dump |

### Recognizing self-unpacking/self-modifying code

```text
Traits:
1. mmap(PROT_READ|PROT_WRITE|PROT_EXEC) call near the entry point
2. Followed immediately by memcpy or a copy loop
3. Then mprotect to change permissions
4. Finally br/jmp to the newly mapped address

Analysis strategy:
1. Find the mmap call -> note the returned address
2. Breakpoint after mprotect(PROT_EXEC)
3. Dump the unpacked memory region
4. Analyze it as a new binary
```

---

## ARM64 (AArch64) reversing quick reference

### Registers

| Register | Purpose |
|--------|------|
| x0-x7 | arguments/return value |
| x8 | indirect result (syscall number) |
| x9-x15 | temporaries |
| x16-x17 | IP0/IP1 (PLT jumps) |
| x18 | platform register (Android: shadow call stack) |
| x19-x28 | callee-saved |
| x29 (FP) | frame pointer |
| x30 (LR) | link register (return address) |
| SP | stack pointer |
| PC | program counter |

### Common instruction patterns

```text
Function prologue:
  stp x29, x30, [sp, #-N]!    # save FP and LR
  mov x29, sp                  # set up frame pointer

Function epilogue:
  ldp x29, x30, [sp], #N      # restore FP and LR
  ret                          # return (br x30)

Syscalls:
  mov x8, #NR                  # syscall number
  svc #0                       # trigger the syscall

Conditional branches:
  cmp x0, #0
  b.eq label                   # branch if equal
  b.ne label                   # branch if not equal
  cbz x0, label                # branch if x0 == 0
  cbnz x0, label               # branch if x0 != 0

Address loading:
  adrp x0, page                # load high bits of page address
  add x0, x0, #offset          # add low 12-bit offset
  ldr x0, [x1, #offset]        # load from memory
```

### Linux ARM64 syscall numbers

| Number | Name | Purpose |
|------|------|------|
| 56 | openat | open a file |
| 63 | read | read |
| 64 | write | write |
| 57 | close | close |
| 222 | mmap | memory mapping |
| 226 | mprotect | change memory permissions |
| 117 | ptrace | process tracing |
| 220 | clone | create process/thread |
| 221 | execve | execute a program |
| 93 | exit | exit |
| 94 | exit_group | exit the process group |

---

## Recognizing common compression/packing algorithms

| Algorithm | Recognition trait | Decompression |
|------|---------|---------|
| **LZSS** | Bitstream + literal/match flags | Custom decompressor (like this report's) |
| **ZLIB/Deflate** | Magic: `78 01`/`78 9C`/`78 DA` | `zlib.decompress()` |
| **GZIP** | Magic: `1F 8B` | `gzip -d` / `gunzip` |
| **LZ4** | Magic: `04 22 4D 18` | `lz4 -d` |
| **LZMA/XZ** | Magic: `FD 37 7A 58 5A 00` (XZ) | `xz -d` / `lzma -d` |
| **Brotli** | No fixed magic; judge by context | `brotli -d` |
| **Zstandard** | Magic: `28 B5 2F FD` | `zstd -d` |
| **UPX** | The string `UPX!` | `upx -d` |
| **Custom** | Unpacking loop at the entry point | Reverse the algorithm, then write a decompressor |

### Clues for identifying custom compression

```text
1. Loop + bit operations near the entry point (shifts, AND, OR)
2. "Sliding window" copy-back (reading backwards from the output buffer) -> LZ family
3. Frequency table / Huffman tree construction -> Deflate/Huffman
4. Fixed-size block processing -> block compression (LZ4/Snappy)
5. Arithmetic-coding traits (interval narrowing) -> LZMA/ANS
```

---

## Linux process injection techniques

### mmap + code injection

```text
Flow:
1. mmap(NULL, size, PROT_READ|PROT_WRITE, MAP_ANON|MAP_PRIVATE, -1, 0)
2. Write shellcode/payload into the mapped region
3. mprotect(addr, size, PROT_READ|PROT_EXEC)  # switch to executable
4. Jump to the mapped address and execute

Traits:
- The mmap return value is saved
- Followed immediately by memcpy or a write loop
- Then mprotect to change permissions
- Finally br/blr to that address
```

### ptrace injection

```text
Flow:
1. ptrace(PTRACE_ATTACH, target_pid)
2. waitpid(target_pid)
3. ptrace(PTRACE_GETREGS, target_pid, &regs)
4. Point regs.pc at the injected code
5. ptrace(PTRACE_SETREGS, target_pid, &regs)
6. ptrace(PTRACE_CONT, target_pid)

Traits:
- Opens /proc/<pid>/mem or uses ptrace
- Reads/modifies the target process registers
- Writes shellcode into the target process space
```

### /proc/self/mem self-modification

```text
Flow:
1. open("/proc/self/mem", O_RDWR)
2. lseek(fd, target_addr, SEEK_SET)
3. write(fd, new_code, size)

Uses:
- Bypass W^X protection (mmap'ed pages cannot be W+X simultaneously)
- Modify its own code segment (.text is normally read-only)
- Patch instructions at runtime
```

---

## Strategy for analyzing large ELF files

For 5MB+ binaries:

```text
1. Fast reconnaissance (5 minutes)
   - file / rabin2 -I -> architecture, type, protections
   - strings | grep -i "error\|fail\|http\|/proc\|/dev" -> key strings
   - rabin2 -i -> imported functions (if any)
   - rabin2 -E -> exported functions

2. Structure analysis (10 minutes)
   - readelf -l -> program headers (LOAD segment layout)
   - Code near the entry point -> any unpacking/decryption
   - Find .init_array -> constructors (may contain anti-debugging)

3. Locate the key logic
   - Start from string cross-references
   - Start from syscalls (mmap/ptrace/open)
   - Start from network functions (connect/send/recv)

4. Divide and conquer
   - If self-unpacking -> unpack first, analyze the payload
   - If multi-module -> analyze in functional blocks
   - Use binary-diff across versions
```

---

## Tool command cheat sheet

```bash
# Basic information
file binary
readelf -h binary          # ELF header
readelf -l binary          # program headers
readelf -S binary          # section headers (if any)
rabin2 -I binary           # combined information

# Strings
strings -a binary | less
rabin2 -z binary           # data-section strings
rabin2 -zz binary          # whole-file strings

# Disassembly
r2 -A binary               # radare2 analysis
objdump -d binary          # GNU disassembly
aarch64-linux-gnu-objdump -d binary  # ARM64 cross-disassembly

# Dynamic analysis
strace -f ./binary         # syscall tracing
ltrace -f ./binary         # library-call tracing
qemu-aarch64 -strace ./binary  # ARM64 emulated execution

# Memory dump
gdb -p <pid> -ex "dump memory out.bin 0xADDR 0xADDR+SIZE" -ex quit

# Repairing a corrupted ELF
# Manually fix e_phnum or patch the corrupted PHDR
python -c "
import struct
with open('binary', 'r+b') as f:
    f.seek(0x38)  # e_phnum offset (64-bit)
    f.write(struct.pack('<H', 2))  # set the correct PHDR count
"
```
