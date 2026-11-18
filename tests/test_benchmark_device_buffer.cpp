#include <cstdio>
#include <vector>
#include "device_buffer.h"
namespace {
struct FakeApi {
  int allocations=0, releases=0, fail_at=0, fail_free=0;
  std::vector<int*> live;
  int success() const { return 0; }
  template<class T> int allocate(T** out, std::size_t) {
    ++allocations; if (allocations==fail_at) return 1;
    *out=reinterpret_cast<T*>(new int(allocations)); live.push_back(reinterpret_cast<int*>(*out)); return 0;
  }
  int release(void* p) {
    ++releases; auto* v=static_cast<int*>(p);
    for(auto i=live.begin();i!=live.end();++i) if(*i==v){live.erase(i);break;}
    delete v; return releases==fail_free?2:0;
  }
};
int failures=0;
void check(bool ok,const char* what){if(!ok){std::fprintf(stderr,"FAIL [device_buffer] %s\n",what);++failures;}}
void partial_failure(){
 FakeApi api; int reported=0;
 auto report=[&](int,const char*){++reported;};
 { bench::DeviceBuffer<FakeApi,int,decltype(report)> a(api,report),b(api,report),c(api,report);
   check(a.allocate(4,"a"),"first allocation");
   check(b.allocate(4,"b"),"second allocation");
   api.fail_at=3; check(!c.allocate(4,"c"),"third allocation should fail"); }
 check(api.releases==2 && api.live.empty(),"partial allocation leaked");
 check(reported==1,"allocation error not reported");
}
void cleanup_failure(){
 FakeApi api; api.fail_free=1; int reported=0;
 auto report=[&](int,const char*){++reported;};
 { bench::DeviceBuffer<FakeApi,int,decltype(report)> a(api,report); check(a.allocate(4,"a"),"allocation"); }
 check(api.releases==1 && api.live.empty(),"cleanup did not release");
 check(reported==1,"cleanup error not reported");
}
}
int main(){partial_failure();cleanup_failure();if(failures)return 1;std::puts("OK [device_buffer]");return 0;}
