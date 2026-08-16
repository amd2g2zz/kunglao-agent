# Kernel Driver Reverse Engineering Reference

> Covers Windows/Linux kernel driver reversing, rootkit analysis, and C/C++ binary pattern recognition.

---

## Windows driver reversing

### Driver types

| Type | Trait | Analysis focus |
|------|------|---------|
| WDM (Windows Driver Model) | Legacy drivers, manual IRP management | DriverEntry -> device creation -> dispatch routines |
| KMDF (Kernel Mode Driver Framework) | Modern framework, event-driven | EvtDriverDeviceAdd -> Queue -> I/O callbacks |
| WDF (Windows Driver Foundation) | Umbrella for KMDF + UMDF | Look for WdfDriverCreate calls |
| Minifilter | File-system filter driver | FltRegisterFilter -> Pre/Post callbacks |

### WDM driver analysis flow

```text
1. Find DriverEntry (entry point)
   - Auto-identified by IDA, or search for IoCreateDevice / IoCreateSymbolicLink

2. Find the device name and symbolic link
   - IoCreateDevice -> DeviceName (e.g., \Device\MyDriver)
   - IoCreateSymbolicLink -> SymLink (e.g., \DosDevices\MyDriver)

3. Find the dispatch routines
   - DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL] = DispatchIoctl
   - This is the entry the user mode calls via DeviceIoControl

4. Analyze IOCTL handling
   - switch(IoControlCode) dispatches different functions
   - IOCTL encoding: CTL_CODE(DeviceType, Function, Method, Access)
   - Method: METHOD_BUFFERED / METHOD_IN_DIRECT / METHOD_OUT_DIRECT / METHOD_NEITHER

5. Hunt for vulnerabilities
   - User-controlled buffer with unchecked length -> overflow
   - METHOD_NEITHER using user pointers directly -> arbitrary read/write
   - Missing IOCTL permission checks -> callable by unprivileged users
```

### IOCTL code decoding

```python
# Decode an IOCTL code
def decode_ioctl(code):
    device_type = (code >> 16) & 0xFFFF
    access = (code >> 14) & 0x3
    function = (code >> 2) & 0xFFF
    method = code & 0x3

    methods = {0: "BUFFERED", 1: "IN_DIRECT", 2: "OUT_DIRECT", 3: "NEITHER"}
    access_types = {0: "ANY", 1: "READ", 2: "WRITE", 3: "READ|WRITE"}

    return f"DevType=0x{device_type:X} Func=0x{function:X} Method={methods[method]} Access={access_types[access]}"

# Example
decode_ioctl(0x80002034)
# DevType=0x8000 Func=0x80D Method=BUFFERED Access=ANY
```

### IDA plugins

| Plugin | Purpose | Link |
|------|------|------|
| **Driver Buddy Reloaded** | Auto-identifies IOCTLs, dispatch routines, device names | https://github.com/VoidSec/DriverBuddyReloaded |
| **WinDbg + IDA** | Kernel debugging + static analysis combo | Built in |
| **FLIRT/Lumina** | Identifies WDK library functions | Built into IDA |

### Reference articles

- [Windows Drivers RE Methodology (VoidSec)](https://voidsec.com/windows-drivers-reverse-engineering-methodology/) — the most complete WDM driver RE methodology
- [Driver Reversing 101](https://eversinc33.com/posts/driver-reversing.html) — WDM vs KMDF comparison
- [Methodology of Reversing Vulnerable Killer Drivers](https://whiteknightlabs.com/2025/10/28/methodology-of-reversing-vulnerable-killer-drivers/) — vulnerable driver analysis

---

## Linux kernel module reversing

### LKM (Loadable Kernel Module) structure

```text
Key functions:
- init_module / module_init -> runs at module load
- cleanup_module / module_exit -> runs at module unload

Key structures:
- struct file_operations -> open/read/write/ioctl of char devices
- struct net_device_ops -> network device operations
- struct block_device_operations -> block device operations
```

### Analysis flow

```text
1. Confirm it is a kernel module
   file module.ko -> "ELF 64-bit ... relocatable" (note: relocatable, not executable)

2. Find the init/exit functions
   readelf -s module.ko | grep -E "init_module|cleanup_module"
   or find module info in the .modinfo section

3. Find the file_operations structure
   Search for register_chrdev / cdev_add / misc_register
   -> find the fops struct -> locate ioctl/read/write handlers

4. Analyze ioctl handling
   unlocked_ioctl / compat_ioctl functions
   -> dispatch via switch(cmd)

5. Hunt for rootkit behavior
   - Modifying sys_call_table -> syscall hooks
   - Modifying the /proc filesystem -> hiding processes/files
   - Registering netfilter hooks -> hiding network connections
   - Modifying the VFS layer -> hiding files
```

### Common rootkit techniques

| Technique | Trait | Detection |
|------|------|---------|
| syscall table hook | Modifies `sys_call_table` entries | Compare the in-memory table with vmlinux on disk |
| VFS hook | Modifies `file_operations` function pointers | Check whether fops pointers point outside the kernel code section |
| Netfilter hook | `nf_register_net_hook` | Walk the netfilter hook list |
| kprobe/ftrace hook | Registers kprobe or ftrace callbacks | Check the ftrace registration list |
| eBPF rootkit | Loads malicious BPF programs | `bpftool prog list` |
| DKOM | Directly modifies kernel objects (process lists) | Walk the task_struct list and compare against /proc |

### Tools

| Tool | Purpose |
|------|------|
| `crash` | Kernel dump analysis |
| `volatility3` | Memory forensics (Linux profile) |
| `dmesg` / `journalctl` | Kernel logs |
| `lsmod` / `/proc/modules` | Loaded module list |
| `modinfo` | Module metadata |
| `strace` | Syscall tracing (user-mode view) |

---

## C/C++ reversing pattern recognition

### Common C patterns

| Source pattern | Disassembly trait |
|---------|-----------|
| `if-else` | `cmp` + `jcc` (conditional jump) |
| `switch-case` | Jump table (`jmp [rax*8 + table]`) or consecutive `cmp` |
| `for` loop | `cmp` + `jl/jle` + loop body + `inc/add` + `jmp` back |
| `while` loop | Condition test at the top of the loop |
| `do-while` | Condition test at the bottom of the loop |
| Function pointer call | `call rax` or `call [reg+offset]` |
| `struct` access | `[reg+fixed offset]` (e.g., `[rdi+0x10]`) |
| `malloc` + use | `call malloc` -> return value in a register -> later accesses via that register+offset |
| String comparison | `call strcmp` or `repe cmpsb` |

### C++-specific patterns

| Source pattern | Disassembly trait |
|---------|-----------|
| **Virtual call** | `mov rax, [rcx]` (load vtable) -> `call [rax+offset]` (call virtual function) |
| **Constructor** | Allocate memory -> store vtable pointer -> initialize members |
| **Destructor** | Clean up members -> may call `operator delete` |
| **this pointer** | The first argument (rcx/rdi) is the object pointer |
| **Inheritance** | The vtable contains parent virtual functions + overrides |
| **Multiple inheritance** | Multiple vtable pointers inside the object (different offsets) |
| **RTTI** | A `type_info` pointer sits before the vtable |
| **Exception handling** | `__cxa_throw` / `_CxxThrowException` |
| **STL containers** | `std::vector`: `{begin, end, capacity}` three-pointer structure |
| **std::string** | Small-string optimization (SSO): short strings inline, long strings heap-allocated |

### vtable reversing method

```text
1. Find the vtable
   - Search for consecutive arrays of function pointers (in .rodata or .rdata)
   - Constructors write the vtable pointer with `mov [rcx], offset vtable`

2. Determine the class hierarchy
   - At vtable -8 there is usually an RTTI pointer (if not stripped)
   - Multiple vtables sharing their first entries -> inheritance relationship

3. Annotate virtual functions
   - vtable[0] is usually the destructor (or deleting destructor)
   - Annotate the rest by offset: vtable[1] = func1, vtable[2] = func2...

4. In IDA
   - Create a struct at the vtable address (each field a function pointer)
   - Annotate `call [rax+offset]` with the virtual function being called
```

### Struct recovery

```text
Method 1: infer from access patterns
  mov eax, [rdi+0x00]  -> field_0: int/ptr (4/8 bytes)
  mov ecx, [rdi+0x08]  -> field_8: int/ptr
  movss xmm0, [rdi+0x10] -> field_10: float

Method 2: infer from sizeof
  call malloc(0x30) -> struct size 0x30 (48 bytes)

Method 3: infer from the constructor
  Constructors initialize every field -> field types and offsets are evident

Method 4: use IDA's "Create struct"
  Select access patterns -> Edit -> Struct -> Create struct from selection
```

---

## Common compiler traits

| Compiler | Identification traits |
|--------|---------|
| MSVC | `_security_cookie` checks, `__fastcall` calling convention, Rich Header |
| GCC | `__stack_chk_fail`, `-fstack-protector`, `.note.GNU-stack` |
| Clang/LLVM | Like GCC but different optimization patterns, `__asan_*` (if sanitizers are on) |
| MinGW | GCC traits + Windows API calls |
| AOSP Clang | Android-specific `__android_log_print`, PGO markers |

### Optimization-level identification

| Optimization level | Traits |
|---------|------|
| -O0 | Lots of redundant mov, every variable on the stack, no inlining |
| -O1 | Basic optimizations, some variables in registers |
| -O2 | Loop unrolling, inlining, tail-call optimization |
| -O3 / -Os | Aggressive inlining, vectorization (SIMD), hard-to-read code |
| PGO | Hot-path optimization, cold code split into `.text.cold` |
| LTO | Cross-module inlining, global dead-code elimination |

---

## Kernel debugging environments

### Windows

```text
Debugger: WinDbg Preview
Connection: network debugging (recommended) or serial port

Target machine setup:
bcdedit /debug on
bcdedit /dbgsettings net hostip:192.168.x.x port:50000

Debugger connection:
WinDbg -> File -> Attach to Kernel -> Net -> Port:50000 Key:xxx

Common commands:
!analyze -v          # automatic crash analysis
lm                   # list loaded modules
!drvobj \Driver\xxx  # inspect a driver object
dt nt!_DRIVER_OBJECT # display the struct
bp module!function   # set a breakpoint
```

### Linux

```text
Debugger: GDB + QEMU or kgdb

QEMU kernel debugging:
qemu-system-x86_64 -kernel bzImage -s -S ...
gdb vmlinux -ex "target remote :1234"

Common commands:
info threads         # kernel threads
lx-symbols           # load kernel symbols (needs scripts/gdb/)
p init_task          # inspect the init process
lx-dmesg             # kernel logs
```

---

## Reference resources

| Resource | Notes | Link |
|------|------|------|
| VoidSec driver RE methodology | Complete Windows WDM driver analysis flow | https://voidsec.com/windows-drivers-reverse-engineering-methodology/ |
| Elastic rootkit series | Linux rootkit taxonomy + detection | https://security-labs.elastic.co/security-labs/linux-rootkits-1-hooked-on-linux |
| Driver Buddy Reloaded | IDA driver analysis plugin | https://github.com/VoidSec/DriverBuddyReloaded |
| LOLDrivers | Known vulnerable driver list | https://www.loldrivers.io/ |
| Windows Driver Samples | Official Microsoft driver samples | https://github.com/microsoft/Windows-driver-samples |
| Linux Kernel Module Programming | Kernel module development tutorial | https://sysprog21.github.io/lkmpg/ |
| Trail of Bits - Devirtualizing C++ | vtable reversing method | https://blog.trailofbits.com/2017/02/13/devirtualizing-c-with-binary-ninja/ |
